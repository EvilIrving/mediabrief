"""通用任务队列：DB 持久化 + 可插拔策略 + SSE 广播。

设计目标：
- 后端管理完整生命周期（刷新不丢状态）
- 策略可插拔（SerialStrategy / ConcurrentStrategy / PriorityStrategy）
- 任何模块可通过 register_handler 注册任务类型
- 前端通过 REST 获取状态，通过 SSE 订阅变更
"""
import asyncio
import json
import logging
from typing import Awaitable, Callable, Optional

from cancellation import CancelledByUser
from db import (
    queue_clear_completed,
    queue_claim_next as _db_claim_next,
    queue_enqueue as _db_enqueue,
    queue_get_state as _db_get_state,
    queue_remove as _db_remove,
    queue_set_cancelled as _db_set_cancelled,
    queue_set_completed as _db_set_completed,
    queue_set_error as _db_set_error,
)

logger = logging.getLogger(__name__)

# ── 策略接口 ──────────────────────────────────────────────────

class QueueStrategy:
    """队列执行策略基类。"""
    async def can_dequeue(self, queue_name: str) -> bool:
        raise NotImplementedError

    async def on_item_start(self, queue_name: str, item_id: str):
        pass

    async def on_item_done(self, queue_name: str, item_id: str):
        pass


class SerialStrategy(QueueStrategy):
    """串行策略：同一队列同时只处理一个任务。"""
    def __init__(self):
        self._active: dict[str, bool] = {}

    async def can_dequeue(self, queue_name: str) -> bool:
        return not self._active.get(queue_name, False)

    async def on_item_start(self, queue_name: str, item_id: str):
        self._active[queue_name] = True

    async def on_item_done(self, queue_name: str, item_id: str):
        self._active[queue_name] = False


class ConcurrentStrategy(QueueStrategy):
    """并发策略：限制同时处理的任务数。"""
    def __init__(self, max_concurrent: int = 3):
        self._max = max_concurrent
        self._counts: dict[str, int] = {}

    async def can_dequeue(self, queue_name: str) -> bool:
        return self._counts.get(queue_name, 0) < self._max

    async def on_item_start(self, queue_name: str, item_id: str):
        self._counts[queue_name] = self._counts.get(queue_name, 0) + 1

    async def on_item_done(self, queue_name: str, item_id: str):
        self._counts[queue_name] = max(0, self._counts.get(queue_name, 1) - 1)


# ── 队列管理器 ────────────────────────────────────────────────

# 任务处理器签名: async (payload: dict) -> dict (result)
TaskHandler = Callable[[dict], Awaitable[dict]]


class TaskQueueManager:
    """通用任务队列管理器。

    用法：
        qm = TaskQueueManager(strategy=SerialStrategy())
        qm.register_handler("rss_summarize", handle_summarize)
        qm.register_handler("rss_download", handle_download)

        # 入队
        await qm.enqueue("rss", "rss_summarize", "feed1:entry1", {...})

        # 前端订阅队列状态
        queue = qm.subscribe("rss")
    """

    def __init__(self, strategy: QueueStrategy | None = None):
        self._strategy = strategy or SerialStrategy()
        self._handlers: dict[str, TaskHandler] = {}
        self._subscribers: dict[str, list[asyncio.Queue]] = {}
        self._worker_lock = asyncio.Lock()
        # 认领闸门锁：把"判定可出队 → 取项 → 置 processing → on_item_start"收成一个原子段。
        # 否则这几步之间的多个 await 会让并发的 worker（历史上因重启/重建会出现多个）
        # 越过串行闸门，重复认领同一项（UNIQUE constraint failed）或同时跑两项。
        self._dequeue_lock = asyncio.Lock()
        self._workers: dict[str, asyncio.Task] = {}
        self._wakeup: dict[str, asyncio.Event] = {}

    def register_handler(self, item_type: str, handler: TaskHandler):
        """注册任务类型处理器。handler 接收 payload，返回 result dict。"""
        self._handlers[item_type] = handler
        logger.info(f"队列处理器已注册: {item_type}")

    def is_registered(self, item_type: str) -> bool:
        """该任务类型是否已注册处理器（入队前校验用）。"""
        return item_type in self._handlers

    # ── 入队 ──────────────────────────────────────────────

    async def enqueue(
        self,
        queue_name: str,
        item_type: str,
        item_key: str,
        payload: dict,
    ) -> dict:
        """入队一个任务。item_key 用于幂等去重。返回 {id, status, duplicate}。"""
        result = await _db_enqueue(queue_name, item_type, item_key, payload)
        if not result.get("duplicate"):
            await self._broadcast_state(queue_name)
            # 唤醒/确保队列处理器存在
            self._wakeup_event(queue_name)
            await self._ensure_worker(queue_name)
        return result

    # ── 队列处理器 ────────────────────────────────────────

    async def _ensure_worker(self, queue_name: str):
        """确保每个队列只有一个后台处理器在运行。"""
        async with self._worker_lock:
            worker = self._workers.get(queue_name)
            if worker and not worker.done():
                return worker

            worker = asyncio.create_task(self._process_loop(queue_name))
            self._workers[queue_name] = worker

            def _cleanup(done_task: asyncio.Task):
                if self._workers.get(queue_name) is done_task:
                    self._workers.pop(queue_name, None)

            worker.add_done_callback(_cleanup)
            return worker

    async def _claim_next(self, queue_name: str):
        """原子地认领下一个可处理项。

        在 ``_dequeue_lock`` 内一次性完成串行闸门判定、取项、置 processing 与
        ``on_item_start``，使并发的多个 worker（或同一 worker 的相邻迭代）不会越过
        闸门重复认领同一项或同时启动两项。返回 ``(item_id, item_type, payload, handler)``
        或 ``None``（无可处理项 / 闸门未放行 / 未知类型已就地标错）。
        """
        async with self._dequeue_lock:
            if not await self._strategy.can_dequeue(queue_name):
                return None

            item = await _db_claim_next(queue_name)
            if not item:
                return None

            item_id = item["id"]
            item_type = item.get("item_type", "")
            payload = item.get("payload", "{}")
            if isinstance(payload, str):
                try:
                    payload = json.loads(payload)
                except (json.JSONDecodeError, TypeError):
                    payload = {}

            handler = self._handlers.get(item_type)
            if not handler:
                logger.error(f"未知任务类型: {item_type} (item={item_id})")
                await _db_set_error(item_id, f"未知任务类型: {item_type}")
                await self._broadcast_state(queue_name)
                return None

            await self._strategy.on_item_start(queue_name, item_id)
            await self._broadcast_state(queue_name)
            return item_id, item_type, payload, handler

    async def _process_loop(self, queue_name: str):
        """队列处理主循环：从 DB 取下一项，执行，广播状态。

        空闲时阻塞在唤醒事件上，而非定时轮询 DB——入队（``enqueue``）会 ``set``
        该事件即时唤醒。保留一个较长的兜底超时，覆盖「判定空闲 → clear 之间被
        入队抢先 set」的丢唤醒竞态（最坏延迟一个超时周期，不会永久卡住）。
        """
        logger.info(f"队列处理器启动: {queue_name}")
        evt = self._wakeup_obj(queue_name)
        while True:
            claimed = await self._claim_next(queue_name)
            if not claimed:
                evt.clear()
                try:
                    await asyncio.wait_for(evt.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    pass
                continue

            item_id, item_type, payload, handler = claimed
            logger.info(f"开始处理队列项: {queue_name}/{item_id} type={item_type}")

            try:
                result = await handler(payload)
                status = result.get("status", "completed") if isinstance(result, dict) else "completed"
                if status == "cancelled":
                    await _db_set_cancelled(item_id, result)
                    logger.info(f"队列项取消: {queue_name}/{item_id}")
                elif status == "error":
                    err_msg = (result.get("error") if isinstance(result, dict) else str(result)) or "未知错误"
                    await _db_set_error(item_id, err_msg)
                    logger.error(f"队列项失败: {queue_name}/{item_id}: {err_msg[:120]}")
                else:
                    await _db_set_completed(item_id, result)
                    logger.info(f"队列项完成: {queue_name}/{item_id}")
            except asyncio.CancelledError:
                logger.info(f"队列项被取消: {queue_name}/{item_id}")
                await _db_set_cancelled(item_id, {"task_id": item_id, "status": "cancelled"})
            except CancelledByUser:
                logger.info(f"队列项被用户取消: {queue_name}/{item_id}")
                await _db_set_cancelled(item_id, {"task_id": item_id, "status": "cancelled"})
            except Exception as e:
                logger.error(f"队列项失败: {queue_name}/{item_id}: {e}", exc_info=True)
                await _db_set_error(item_id, str(e))
            finally:
                await self._strategy.on_item_done(queue_name, item_id)
                await self._broadcast_state(queue_name)

    # ── SSE 订阅 ──────────────────────────────────────────

    def subscribe(self, queue_name: str) -> asyncio.Queue:
        """订阅队列状态变更。返回 maxsize=1 的队列。"""
        q = asyncio.Queue(maxsize=1)
        if queue_name not in self._subscribers:
            self._subscribers[queue_name] = []
        self._subscribers[queue_name].append(q)
        # 立即发送当前状态
        asyncio.create_task(self._send_current_state(queue_name, q))
        return q

    def unsubscribe(self, queue_name: str, q: asyncio.Queue):
        """取消订阅。"""
        subs = self._subscribers.get(queue_name, [])
        if q in subs:
            subs.remove(q)

    async def _send_current_state(self, queue_name: str, q: asyncio.Queue):
        """向新订阅者发送当前队列状态。"""
        state = await _db_get_state(queue_name)
        try:
            q.put_nowait(json.dumps(state, ensure_ascii=False))
        except asyncio.QueueFull:
            try:
                q.get_nowait()
            except asyncio.QueueEmpty:
                pass
            try:
                q.put_nowait(json.dumps(state, ensure_ascii=False))
            except asyncio.QueueFull:
                pass

    async def _broadcast_state(self, queue_name: str):
        """向所有订阅者广播最新队列状态。"""
        subs = self._subscribers.get(queue_name, [])
        if not subs:
            return  # 无订阅者时跳过 DB 查询 + 序列化（每个阶段都会触发广播）
        state = await _db_get_state(queue_name)
        data = json.dumps(state, ensure_ascii=False)
        bad = []
        for q in subs:
            try:
                q.put_nowait(data)
            except asyncio.QueueFull:
                try:
                    q.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                try:
                    q.put_nowait(data)
                except asyncio.QueueFull:
                    bad.append(q)
            except Exception:
                bad.append(q)
        for q in bad:
            try:
                subs.remove(q)
            except ValueError:
                pass

    async def recover_stale_processing(self, queue_name: str) -> int:
        """恢复启动时残留的 processing 项（服务器异常退出所致）。

        将无对应有效 task 的 processing 项标为 error；
        有对应 task 但 task 已终态的项也标为 error；
        其余（task 仍在 processing 但服务重启了）降回 queued 重新调度。
        """
        from db import queue_recover_stale
        count = await queue_recover_stale(queue_name)
        if count:
            await self._broadcast_state(queue_name)
        # 恢复后可能有项被降回 queued；worker 只在 enqueue 时惰性启动，重启后
        # 没有新入队就没人处理这些项——这里显式确保 worker 在跑并叫醒它。
        await self._ensure_worker(queue_name)
        self._wakeup_event(queue_name)
        return count

    # ── 工具 ──────────────────────────────────────────────

    def _wakeup_obj(self, queue_name: str) -> asyncio.Event:
        """获取或创建唤醒事件（处理循环空闲时等待它）。"""
        evt = self._wakeup.get(queue_name)
        if evt is None:
            evt = asyncio.Event()
            self._wakeup[queue_name] = evt
        return evt

    def _wakeup_event(self, queue_name: str) -> asyncio.Event:
        """唤醒处理循环（入队后调用）：set 事件即时叫醒空闲的 worker。"""
        evt = self._wakeup_obj(queue_name)
        evt.set()
        return evt

    async def get_state(self, queue_name: str) -> dict:
        """获取队列完整状态（REST 端点用）。"""
        return await _db_get_state(queue_name)

    async def remove_item(self, queue_name: str, item_id: str):
        """从队列中移除一项（按 queue item id）。"""
        await _db_remove(item_id)
        await self._broadcast_state(queue_name)

    async def get_stats(self, queue_name: str) -> dict:
        """按状态聚合计数 + 队列长度（轻量）。"""
        from db import queue_stats as _db_queue_stats
        return await _db_queue_stats(queue_name)

    async def list_items(self, queue_name: str, status: str = "", limit: int = 50, offset: int = 0) -> dict:
        """分页 / 按状态过滤列出队列项。"""
        from db import queue_list_items as _db_queue_list_items
        return await _db_queue_list_items(queue_name, status, limit, offset)

    async def get_item(self, item_id: str) -> dict | None:
        """单项详情（安全投影，不含 payload）。"""
        from db import queue_get_item as _db_queue_get_item
        return await _db_queue_get_item(item_id)

    async def get_item_payload(self, item_id: str) -> dict | None:
        """读取原始 payload + item_type（内部用，重试等场景）。"""
        from db import queue_get_item_payload as _db_queue_get_item_payload
        return await _db_queue_get_item_payload(item_id)

    async def cancel_item(self, queue_name: str, item_id: str) -> bool:
        """取消一项并彻底杀干净（含运行中的下载/ffmpeg/Whisper），然后删除记录。

        统一两条历史取消路径：排队中直接删；运行中先触发取消令牌
        （killpg 子进程 + 置协作标志），再取消其 asyncio 任务以解开等待，
        最后按用户约定删除队列记录与任务记录。
        """
        import cancellation

        item = await self.get_item(item_id)
        if not item:
            return False
        task_id = item.get("task_id") or ""
        status = item.get("status")

        if status == "processing" and task_id:
            # 触发协作取消：杀掉已登记子进程并置标志，让深层循环尽快退出。
            cancellation.cancel(task_id)
            from task_store import active_tasks
            running = active_tasks.get(task_id)
            if running and not running.done():
                running.cancel()  # 解开对 asyncio 等待的阻塞
                # 等待 pipeline 真正停掉再返回：worker 仍卡在 await handler 里、
                # 持有 SerialStrategy 的 _active 锁；不等它退出就删记录并返回，会
                # 造成「前端以为取消了、worker 还堵着、下一个任务摘不下来」的窗口。
                # 又因 Whisper 模型全程热复用、取消只在段边界生效（cancellation.py
                # D3），不能提前释放锁让下一个任务并发跑同一模型——只能等。
                # asyncio.wait 等待其结束而不向本协程抛出 CancelledError。
                await asyncio.wait({running})

        # 删除队列记录与对应任务记录（用户约定：取消即删除）。
        await _db_remove(item_id)
        if task_id:
            try:
                from db import delete_task as _db_delete_task
                await _db_delete_task(task_id)
            except Exception as e:
                logger.warning(f"删除已取消任务记录失败 {task_id}: {e}")
        await self._broadcast_state(queue_name)
        return True

    async def remove_task_by_id(self, queue_name: str, task_id: str):
        """从队列中移除指定 task_id 的项。"""
        from db import queue_remove_by_task_id as _db_remove_by_task_id
        count = await _db_remove_by_task_id(queue_name, task_id)
        if count:
            await self._broadcast_state(queue_name)
        return count

    async def clear_completed(self, queue_name: str) -> int:
        """清除已完成/错误的队列项。"""
        count = await queue_clear_completed(queue_name)
        if count:
            await self._broadcast_state(queue_name)
        return count


# ── 全局单例 ─────────────────────────────────────────────────

queue_manager = TaskQueueManager(strategy=SerialStrategy())
