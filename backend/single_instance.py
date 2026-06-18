"""后端单实例锁。

同一个数据目录只允许一个 FastAPI 后端完成 startup。否则多个进程各自持有
TaskQueueManager/SerialStrategy 的内存锁，会跨进程并发认领队列项。
"""
import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

_lock_file = None
_lock_path: Path | None = None


def _lock_nonblocking(file_obj) -> bool:
    if sys.platform == "win32":
        import msvcrt
        try:
            # 锁住 1 byte 即可；文件句柄存活期间独占。
            msvcrt.locking(file_obj.fileno(), msvcrt.LK_NBLCK, 1)
            return True
        except OSError:
            return False

    import fcntl
    try:
        fcntl.flock(file_obj.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except BlockingIOError:
        return False
    except OSError:
        return False


def _unlock(file_obj):
    if sys.platform == "win32":
        import msvcrt
        try:
            file_obj.seek(0)
            msvcrt.locking(file_obj.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
        return

    import fcntl
    try:
        fcntl.flock(file_obj.fileno(), fcntl.LOCK_UN)
    except OSError:
        pass


def acquire_instance_lock(data_dir: Path) -> None:
    """获取当前数据目录的独占后端锁。失败时抛 RuntimeError。"""
    global _lock_file, _lock_path
    if _lock_file is not None:
        return

    data_dir.mkdir(parents=True, exist_ok=True)
    lock_path = data_dir / "backend.instance.lock"
    file_obj = open(lock_path, "a+", encoding="utf-8")
    if not _lock_nonblocking(file_obj):
        file_obj.seek(0)
        existing = file_obj.read().strip()
        file_obj.close()
        msg = (
            "已有 MediaBrief 后端实例在使用该数据目录；"
            "请先运行 `pnpm stop` 或关闭桌面应用后再启动。"
        )
        if existing:
            msg += f" lock={existing}"
        logger.error(msg)
        raise RuntimeError(msg)

    file_obj.seek(0)
    file_obj.truncate()
    file_obj.write(f"pid={os.getpid()} cwd={os.getcwd()}\n")
    file_obj.flush()
    _lock_file = file_obj
    _lock_path = lock_path
    logger.info("已获取后端单实例锁: %s", lock_path)


def release_instance_lock() -> None:
    """释放后端单实例锁。"""
    global _lock_file, _lock_path
    if _lock_file is None:
        return
    try:
        _unlock(_lock_file)
        _lock_file.close()
        logger.info("已释放后端单实例锁: %s", _lock_path)
    finally:
        _lock_file = None
        _lock_path = None
