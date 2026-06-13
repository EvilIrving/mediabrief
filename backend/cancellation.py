# ╔══════════════════════════════════════════════════════════════════════╗
# ║ 决策记录(本轮队列/取消重构的关键结论与理由)                          ║
# ╠══════════════════════════════════════════════════════════════════════╣
# ║ D1 不引入外部队列库(Celery/ARQ/SAQ),保留进程内手写队列。            ║
# ║    理由:唯一能"真杀运行中任务"的 Celery 靠 prefork 子进程 + broker, ║
# ║    对本地单用户桌面应用(PyInstaller 打包)过重且难打包;ARQ/SAQ 的    ║
# ║    abort 用的就是 asyncio 取消,杀不掉跑 yt-dlp/Whisper 的线程,换库   ║
# ║    不解决问题。瓶颈不在队列框架,而在底层三个库的活进程内不可打断。    ║
# ║ D2 取消改用各上游库的官方机制,而非把整条 pipeline 搬进子进程:        ║
# ║    · Whisper  → 惰性 generator,段间检查标志 break + segments.close() ║
# ║    · yt-dlp   → progress/postprocessor 钩子里 raise DownloadCancelled ║
# ║    · ffmpeg   → 外部子进程,start_new_session 建进程组,killpg 整组杀  ║
# ║ D3 Whisper 不做进程隔离 → 模型全程热复用、零冷启动;代价是取消只能在   ║
# ║    段边界生效(当前正在解的一段需先跑完),符合其惰性生成器语义。      ║
# ║ D4 取消语义 = 删除记录,但必须杀干净底层进程(下载/ffmpeg/Whisper),  ║
# ║    不能像旧实现那样只删状态、让线程在后台空跑(用户明确要求)。        ║
# ║ D5 顺手修复:Whisper 逐段迭代原本跑在主事件循环、转录期间阻塞 SSE/其它 ║
# ║    请求 → 已整体挪进 asyncio.to_thread。                              ║
# ║ D6 history 列表不再返回 script 全文(一次百条可达兆级),改由           ║
# ║    GET /api/task/{id}/transcript 按需取。                            ║
# ║ D7 不做兼容设计(用户要求):旧 DELETE /api/queue/{item_id} 已移除,    ║
# ║    队列接口统一为 stats / items / item detail / cancel。             ║
# ╚══════════════════════════════════════════════════════════════════════╝
"""任务取消内核：协作式取消标志 + 子进程组回收。

设计依据(各上游库的官方取消机制)：
- faster-whisper：``transcribe()`` 返回惰性 generator，迭代到段与段之间检查标志，
  ``break`` + ``segments.close()`` 即可停止后续解码，模型留在内存中热复用。
- yt-dlp：在 ``progress_hooks`` / ``postprocessor_hooks`` 中 ``raise DownloadCancelled``
  可干净中断下载阶段。
- ffmpeg：外部子进程，只能靠信号。用 ``start_new_session=True`` 让其成为进程组组长，
  取消时 ``killpg`` 整组回收(含其派生的孙子进程)。

一个 :class:`CancelToken` 贯穿某个 task 的三个阶段：
- ``check()`` / ``is_cancelled()`` 供 CPU 密集循环协作检查；
- ``register_process()`` 登记可被信号杀死的子进程；
- ``cancel()`` 由队列层在用户取消时调用：置标志并杀掉所有登记子进程。

通过 :class:`contextvars.ContextVar` 把当前 token 传到深层代码(transcriber /
video_processor)，避免在每个函数签名里穿透传递。``asyncio.to_thread`` 会复制
当前 context，故工作线程内同样能读到 token。
"""
from __future__ import annotations

import contextvars
import logging
import os
import signal
import subprocess
import threading

logger = logging.getLogger(__name__)

# 深层代码通过 current() 读取，无需改函数签名。
_current: "contextvars.ContextVar[CancelToken | None]" = contextvars.ContextVar(
    "cancel_token", default=None
)
# 队列层通过 task_id 反查 token 以触发外部取消。
_registry: "dict[str, CancelToken]" = {}


class CancelledByUser(Exception):
    """用户主动取消任务时抛出，区别于真正的错误。"""


class CancelToken:
    """单个 task 的取消令牌：协作标志 + 已登记子进程。"""

    def __init__(self, task_id: str):
        self.task_id = task_id
        self._event = threading.Event()
        self._procs: list[subprocess.Popen] = []
        self._lock = threading.Lock()

    def is_cancelled(self) -> bool:
        return self._event.is_set()

    def check(self):
        """在密集循环里调用：已取消则抛 CancelledByUser。"""
        if self._event.is_set():
            raise CancelledByUser()

    def register_process(self, proc: subprocess.Popen):
        """登记一个可被信号杀死的子进程。若已取消则立即杀。"""
        with self._lock:
            if self._event.is_set():
                _kill_process(proc)
                return
            self._procs.append(proc)

    def unregister_process(self, proc: subprocess.Popen):
        with self._lock:
            try:
                self._procs.remove(proc)
            except ValueError:
                pass

    def cancel(self):
        """触发取消：置标志 + 杀掉所有登记子进程(进程组)。"""
        self._event.set()
        with self._lock:
            procs = list(self._procs)
        for proc in procs:
            _kill_process(proc)


def _kill_process(proc: subprocess.Popen):
    """杀掉子进程；POSIX 下按进程组杀以连带回收 ffmpeg 等孙子进程。"""
    try:
        if proc.poll() is not None:
            return
        if os.name == "posix":
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            except ProcessLookupError:
                return
        else:
            proc.terminate()
    except Exception as e:  # noqa: BLE001 — 杀进程尽力而为，不应反过来炸掉调用方
        logger.warning("终止子进程失败 pid=%s: %s", getattr(proc, "pid", "?"), e)


# ── 生命周期(队列层使用) ────────────────────────────────────

def create(task_id: str) -> CancelToken:
    """为 task 创建并登记 token，同时绑定到当前 context。"""
    token = CancelToken(task_id)
    _registry[task_id] = token
    _current.set(token)
    return token


def discard(task_id: str):
    _registry.pop(task_id, None)


def get(task_id: str) -> "CancelToken | None":
    return _registry.get(task_id)


def cancel(task_id: str) -> bool:
    """外部触发取消。返回是否存在对应 token。"""
    token = _registry.get(task_id)
    if token is None:
        return False
    token.cancel()
    return True


def current() -> "CancelToken | None":
    """深层代码读取当前 task 的 token(可能为 None)。"""
    return _current.get()
