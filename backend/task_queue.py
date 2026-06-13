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

from db import (
    queue_clear_completed,
    queue_enqueue as _db_enqueue,
    queue_get_next as _db_get_next,
    queue_get_state as _db_get_state,
    queue_remove as _db_remove,
    queue_set_cancelled as _db_set_cancelled,
    queue_set_completed as _db_set_completed,
    queue_set_error as _db_set_error,
    queue_set_processing as _db_set_processing,
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
        self._workers: dict[str, asyncio.Task] = {}
        self._wakeup: dict[str, asyncio.Event] = {}

    def register_handler(self, item_type: str, handler: TaskHandler):
        """注册任务类型处理器。handler 接收 payload，返回 result dict。"""
        self._handlers[item_type] = handler
        logger.info(f"队列处理器已注册: {item_type}")

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

    async def _process_loop(self, queue_name: str):
        """队列处理主循环：从 DB 取下一项，执行，广播状态。"""
        logger.info(f"队列处理器启动: {queue_name}")
        while True:
            if not await self._strategy.can_dequeue(queue_name):
                await asyncio.sleep(0.2)
                continue

            item = await _db_get_next(queue_name)
            if not item:
                await asyncio.sleep(1.0)
                continue

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
                continue

            await _db_set_processing(item_id, item_id)
            await self._strategy.on_item_start(queue_name, item_id)
            await self._broadcast_state(queue_name)
            logger.info(f"开始处理队列项: {queue_name}/{item_id} type={item_type}")

            try:
                result = await handler(payload)
                if isinstance(result, dict) and result.get("status") == "cancelled":
                    await _db_set_cancelled(item_id, result)
                    logger.info(f"队列项取消: {queue_name}/{item_id}")
                else:
                    await _db_set_completed(item_id, result)
                    logger.info(f"队列项完成: {queue_name}/{item_id}")
            except asyncio.CancelledError:
                logger.info(f"队列项被取消: {queue_name}/{item_id}")
                await _db_set_cancelled(item_id, {"task_id": item_id, "status": "cancelled"})
            except Exception as e:
                logger.error(f"队列项失败: {queue_name}/{item_id}: {e}")
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
        state = await _db_get_state(queue_name)
        data = json.dumps(state, ensure_ascii=False)
        subs = self._subscribers.get(queue_name, [])
        if not subs:
            return
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

    # ── 工具 ──────────────────────────────────────────────

    def _wakeup_event(self, queue_name: str) -> asyncio.Event:
        """获取或创建唤醒事件（用于通知处理循环有新任务）。"""
        if queue_name not in self._wakeup:
            self._wakeup[queue_name] = asyncio.Event()
        evt = self._wakeup[queue_name]
        evt.set()
        return evt

    async def get_state(self, queue_name: str) -> dict:
        """获取队列完整状态（REST 端点用）。"""
        return await _db_get_state(queue_name)

    async def remove_item(self, queue_name: str, item_id: str):
        """从队列中移除一项（按 queue item id）。"""
        await _db_remove(item_id)
        await self._broadcast_state(queue_name)

    async def remove_task_by_id(self, queue_name: str, task_id: str):
        """从队列中移除指定 task_id 的项。"""
        from db import queue_remove_by_task_id as _db_remove_by_task_id
        count = await _db_remove_by_task_id(queue_name, task_id)
        if count:
            await self._broadcast_state(queue_name)
        return count

    async def clear_completed(self, queue_name: str) -> int:
        """清除已完成/错误的队列项。"""
        count = await _db_clear_completed(queue_name)
        if count:
            await self._broadcast_state(queue_name)
        return count


# ── 全局单例 ─────────────────────────────────────────────────

queue_manager = TaskQueueManager(strategy=SerialStrategy())
