"""应用装配层：创建 FastAPI app、挂载中间件与静态资源、注册路由。

业务逻辑分层：
- services.py   依赖/服务层（处理器单例、上传配置）
- pipeline.py   编排层（转录后处理管线与后台任务执行器）
- routers/      HTTP 层（core / transcribe / downloads / rss）
- task_store.py 任务状态、阶段进度与 SSE 广播
"""
import logging
import threading

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from task_store import PROJECT_ROOT
from routers import core, downloads, export, rss, transcribe

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="AI Transcriber", version="1.0.0")

# CORS中间件配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 挂载静态文件
app.mount("/static", StaticFiles(directory=str(PROJECT_ROOT / "static")), name="static")

# 注册路由
app.include_router(core.router)
app.include_router(transcribe.router)
app.include_router(downloads.router)
app.include_router(rss.router)
app.include_router(export.router)


# ── Whisper 模型预热状态 ──
_model_ready = threading.Event()
_model_error: str | None = None


# ── 在 import 阶段就启动 Whisper 预热的后台线程，不阻塞 uvicorn 启动 ──
def _start_prewarm_thread():
    """延迟导入并后台预热 Whisper 模型"""
    def _prewarm():
        global _model_error
        try:
            from services import transcriber as _t
            logger.info("🔥 后台预热 Whisper 模型（首次运行将自动下载）...")
            _t._load_model()
            _model_ready.set()
            logger.info("✅ Whisper 模型就绪")
        except Exception as e:
            _model_error = str(e)
            logger.warning(f"⚠️  Whisper 模型预热失败（首次转录时将重试）: {e}")
    threading.Thread(target=_prewarm, daemon=True).start()

_start_prewarm_thread()


@app.get("/api/model-status")
async def model_status():
    """查询 Whisper 模型状态，供前端展示模型就绪指示。"""
    return {
        "whisper_ready": _model_ready.is_set(),
        "whisper_error": _model_error,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
