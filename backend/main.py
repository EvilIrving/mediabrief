"""应用装配层：创建 FastAPI app、挂载中间件与静态资源、注册路由。

业务逻辑分层：
- services.py   依赖/服务层（处理器单例、上传配置）
- pipeline.py   编排层（转录后处理管线与后台任务执行器）
- routers/      HTTP 层（core / transcribe / downloads / rss）
- task_store.py 任务状态、阶段进度与 SSE 广播
"""
import logging
import threading
from time import perf_counter

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from logging_config import configure_logging
from app_version import APP_VERSION

LOG_FILE = configure_logging()
logger = logging.getLogger(__name__)
logger.info("日志输出到 %s", LOG_FILE)

from db import init_db  # noqa: E402
from single_instance import acquire_instance_lock, release_instance_lock  # noqa: E402
from task_store import PROJECT_ROOT, TEMP_DIR  # noqa: E402
import task_handlers  # noqa: F401,E402
from routers import bots, core, downloads, export, queue, recovery, rss, settings, transcribe, tts  # noqa: E402

app = FastAPI(title="MediaBrief", version=APP_VERSION)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    started = perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
        raise

    if request.url.path.startswith("/api") or response.status_code >= 500:
        elapsed_ms = (perf_counter() - started) * 1000
        level = logging.INFO
        if response.status_code >= 500:
            level = logging.ERROR
        elif response.status_code >= 400:
            level = logging.WARNING
        client_host = request.client.host if request.client else "-"
        logger.log(
            level,
            "%s %s from %s -> %s (%.1fms)",
            request.method,
            request.url.path,
            client_host,
            response.status_code,
            elapsed_ms,
        )
    return response


@app.on_event("startup")
async def on_startup():
    acquire_instance_lock(TEMP_DIR)
    await init_db()
    # 清扫崩溃/取消遗留的中间文件（仅中间产物，不碰历史与用户下载）。
    try:
        import asyncio
        from task_store import cleanup_stale_temp
        await asyncio.to_thread(cleanup_stale_temp)
    except Exception as e:
        logger.warning("启动清扫临时文件失败: %s", e)
    # 恢复上次异常退出残留的 processing 队列项（服务重启时状态已失序）。
    try:
        from task_queue import queue_manager
        fixed = await queue_manager.recover_stale_processing("tasks")
        if fixed:
            logger.info("启动恢复 %d 个残留 processing 队列项", fixed)
        fixed_rss = await queue_manager.recover_stale_processing("rss")
        if fixed_rss:
            logger.info("启动恢复 %d 个残留 RSS processing 队列项", fixed_rss)
    except Exception as e:
        logger.warning("启动队列恢复失败: %s", e)
    # 恢复上次保存的 Bot 配置（持久化在 app_config 表，重启不丢）
    try:
        from settings_store import migrate_legacy_bot_configs
        from bots import bot_manager
        await migrate_legacy_bot_configs()
        await bot_manager.restore_from_db()
    except Exception as e:
        logger.warning("启动 Bot 配置恢复失败: %s", e)
    _start_prewarm_thread()


@app.on_event("shutdown")
async def on_shutdown():
    """服务停止时(开发模式 Ctrl+C / 桌面应用退出触发的优雅关闭)，
    取消所有进行中的任务并杀掉其登记的子进程，避免 ffmpeg 等孤儿进程残留。"""
    import cancellation
    cancellation.cancel_all()
    # 停止所有常驻 Bot 长连接，避免 httpx 轮询协程残留。
    try:
        from bots import bot_manager
        await bot_manager.shutdown()
    except Exception as e:
        logger.warning("停止 Bot 失败: %s", e)
    release_instance_lock()

# CORS 中间件配置
# 只允许桌面应用本地来源 + 开发 Vite 服务器，避免恶意网站通过 localhost fetch 读取数据
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:8000",
        "http://localhost:8000",
        "http://127.0.0.1:5173",
        "http://localhost:5173",
    ],
    allow_origin_regex=r"http://(127\.0\.0\.1|localhost):\d+",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 挂载静态文件。static/ 在 .gitignore 中、不入仓库，新克隆的环境没有该目录，
# StaticFiles 会因目录缺失直接抛 RuntimeError 让服务无法启动——故在此确保其存在。
_static_dir = PROJECT_ROOT / "static"
_static_dir.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")

# 注册路由
app.include_router(core.router)
app.include_router(transcribe.router)
app.include_router(downloads.router)
app.include_router(rss.router)
app.include_router(queue.router)
app.include_router(recovery.router)
app.include_router(export.router)
app.include_router(settings.router)
app.include_router(bots.router)
app.include_router(tts.router)


# ── 应用启动时启动 Whisper 预热后台线程，不阻塞主窗口 ──
def _start_prewarm_thread():
    """先自动准备默认大模型，再在 MLX 专用线程预热；全程不阻塞主窗口。"""
    def _prewarm():
        try:
            from transcriber import run_on_mlx_thread_sync
            from whisper_models import (
                DEFAULT_MODEL,
                ensure_default_model_async,
                get_transcriber,
                wait_for_default_model,
            )
            ensure_default_model_async()
            if not wait_for_default_model():
                logger.warning("默认 Whisper 模型尚不可用，跳过预热并继续后台恢复")
                return
            transcriber = get_transcriber(DEFAULT_MODEL)
            logger.info("🔥 后台预热默认 Whisper 模型 %s...", DEFAULT_MODEL)
            # 预热必须跑在专用 MLX 线程上：否则在此预热线程上绑定的 GPU stream，
            # 后续转录换线程访问会触发 MLX 抛 C++ 异常并 abort 整个进程。
            run_on_mlx_thread_sync(transcriber._load_model)
            logger.info("✅ 默认 Whisper 模型已下载并预热")
        except Exception as e:
            logger.warning("⚠️  Whisper 模型预热失败（下载线程仍会自动重试）: %s", e)
    threading.Thread(target=_prewarm, daemon=True).start()

@app.get("/api/model-status")
async def model_status():
    """查询默认大模型的下载/续传状态，供前端无感展示初始化进度。"""
    from whisper_models import default_model_status, ensure_default_model_async

    ensure_default_model_async()
    status = default_model_status()
    return {
        **status,
        "whisper_ready": status["ready"],
        "whisper_error": status["error"],
    }


@app.post("/api/model-status/retry")
async def retry_model_preparation():
    """立即重试默认模型准备；正常情况下网络恢复后后台也会自动继续。"""
    from whisper_models import default_model_status, retry_default_model_async

    retry_default_model_async()
    status = default_model_status()
    return {
        **status,
        "whisper_ready": status["ready"],
        "whisper_error": status["error"],
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, log_config=None, access_log=True)
