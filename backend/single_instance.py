"""后端单实例锁。

同一个数据目录只允许一个 FastAPI 后端完成 startup。否则多个进程各自持有
TaskQueueManager/SerialStrategy 的内存锁，会跨进程并发认领队列项。
"""
import json
import logging
import os
import sys
import threading
from collections.abc import Mapping
from pathlib import Path
from typing import TextIO

logger = logging.getLogger(__name__)

_registry_lock = threading.RLock()
_lock_file: TextIO | None = None
_lock_path: Path | None = None
_lock_owners: set[str] = set()
_owner_metadata: dict[str, dict[str, object]] = {}


def _lock_nonblocking(file_obj) -> bool:
    if sys.platform == "win32":
        import msvcrt
        try:
            # msvcrt 从当前文件位置开始加锁，每次都固定锁第 0 字节。
            file_obj.seek(0)
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


def _normalize_owner(owner: str) -> str:
    if not isinstance(owner, str) or not owner.strip():
        raise ValueError("instance lock owner 不能为空")
    return owner.strip()


def _write_metadata_unlocked() -> None:
    """更新锁文件中的诊断信息；失败不影响已获取的系统锁。"""
    if _lock_file is None:
        return
    payload = {
        "pid": os.getpid(),
        "cwd": os.getcwd(),
        "owners": {
            owner: _owner_metadata.get(owner, {})
            for owner in sorted(_lock_owners)
        },
    }
    try:
        _lock_file.seek(0)
        _lock_file.truncate()
        json.dump(payload, _lock_file, ensure_ascii=False, default=str)
        _lock_file.write("\n")
        _lock_file.flush()
    except OSError as exc:
        logger.warning("更新单实例锁诊断信息失败: %s", exc)


def acquire_instance_lock(
    data_dir: Path,
    owner: str = "backend",
    metadata: Mapping[str, object] | None = None,
) -> bool:
    """为 ``owner`` 获取当前数据目录的独占锁。

    ``owner`` 是幂等的逻辑所有者，不做引用计数。同一进程可以让
    ``launcher`` 和 ``backend`` 共享同一个系统锁；只有最后一个 owner
    释放时才会真正解锁。成功返回 ``True``，此时该 owner 一定已登记；
    其他进程已持锁时抛出面向用户的 ``RuntimeError``。
    """
    global _lock_file, _lock_path
    normalized_owner = _normalize_owner(owner)
    initial_metadata = dict(metadata or {})

    with _registry_lock:
        data_dir = Path(data_dir)
        data_dir.mkdir(parents=True, exist_ok=True)
        lock_path = (data_dir / "backend.instance.lock").resolve()

        if _lock_file is not None:
            if _lock_path != lock_path:
                raise RuntimeError(
                    "当前进程已为另一个 MediaBrief 数据目录持有实例锁"
                )
            _lock_owners.add(normalized_owner)
            if initial_metadata:
                _owner_metadata.setdefault(normalized_owner, {}).update(initial_metadata)
            else:
                _owner_metadata.setdefault(normalized_owner, {})
            _write_metadata_unlocked()
            logger.debug("已登记单实例锁 owner=%s: %s", normalized_owner, lock_path)
            return True

        file_obj = open(lock_path, "a+", encoding="utf-8")
        if not _lock_nonblocking(file_obj):
            # Windows 的字节区间锁可能同时阻止第二个进程读取该区间；
            # 诊断 metadata 读不到时仍应返回统一的用户提示。
            try:
                file_obj.seek(0)
                existing = file_obj.read().strip()
            except OSError:
                existing = ""
            finally:
                file_obj.close()
            message = (
                "MediaBrief 已在运行。请切换到已打开的窗口；"
                "如果窗口没有出现，请先完全退出 MediaBrief 后再试。"
            )
            if existing:
                logger.error("单实例锁冲突: %s; lock=%s", message, existing)
            else:
                logger.error("单实例锁冲突: %s", message)
            raise RuntimeError(message)

        _lock_file = file_obj
        _lock_path = lock_path
        _lock_owners.add(normalized_owner)
        _owner_metadata[normalized_owner] = initial_metadata
        _write_metadata_unlocked()
        logger.info("已获取单实例锁 owner=%s: %s", normalized_owner, lock_path)
        return True


def update_instance_lock_metadata(owner: str = "backend", **metadata: object) -> bool:
    """更新 owner 的轻量诊断信息；该 owner 未持锁时返回 ``False``。"""
    normalized_owner = _normalize_owner(owner)
    with _registry_lock:
        if _lock_file is None or normalized_owner not in _lock_owners:
            return False
        _owner_metadata.setdefault(normalized_owner, {}).update(metadata)
        _write_metadata_unlocked()
        return True


def release_instance_lock(owner: str = "backend") -> bool:
    """释放 owner 的逻辑所有权；owner 未持有时返回 ``False``。"""
    global _lock_file, _lock_path
    normalized_owner = _normalize_owner(owner)

    with _registry_lock:
        if _lock_file is None or normalized_owner not in _lock_owners:
            return False

        _lock_owners.remove(normalized_owner)
        _owner_metadata.pop(normalized_owner, None)
        if _lock_owners:
            _write_metadata_unlocked()
            logger.debug("已释放单实例锁 owner=%s，其他 owner 仍持有", normalized_owner)
            return True

        file_obj = _lock_file
        lock_path = _lock_path
        try:
            _unlock(file_obj)
            file_obj.close()
            logger.info("已释放单实例锁 owner=%s: %s", normalized_owner, lock_path)
        finally:
            _lock_file = None
            _lock_path = None
            _owner_metadata.clear()
        return True
