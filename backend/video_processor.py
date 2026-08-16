import os
import re
import math
import shutil
import uuid
import asyncio
import subprocess
import yt_dlp
import logging
from contextvars import ContextVar
from pathlib import Path
from typing import Optional

import cancellation
from cancellation import CancelledByUser
from exceptions import MediaExtractionError
from media_contracts import (
    ExtractionAction,
    ExtractionFailure,
    ExtractionFailureKind,
    ExtractionStage,
    SubtitleFetchResult,
    SubtitleFetchStatus,
    sanitize_diagnostic,
    sanitize_source_reference,
)
from platforms import resolve_adapter

logger = logging.getLogger(__name__)

_REQUEST_COOKIE_OPTS: ContextVar[dict | None] = ContextVar("video_processor_cookie_opts", default=None)
def _download_format_id(fid: str, has_audio: bool) -> str:
    """DASH 视频轨没有音轨时，下载时自动拼 bestaudio，避免下到无声画面。"""
    if has_audio or not fid or "+" in fid or "/" in fid:
        return fid
    return f"{fid}+bestaudio"


class _YDLPLogger:
    """把 yt-dlp 的输出全部接到 Python logging，避免它直接写进程的 stdout/stderr。

    根因：在 ``uvicorn --reload`` / ``pnpm dev`` 下，worker 的 stdout 是连到 reloader
    的**管道**而非终端。yt-dlp 默认会往 stdout 打进度条/信息；两个下载并发时把管道写满，
    某次写入失败就抛 ``[Errno 32] Broken pipe``，导致"第二个任务"下载失败。
    指定 logger（再配合 noprogress/no_color）后，yt-dlp 不再触碰原始管道，问题消除。
    """

    def debug(self, msg):
        # yt-dlp 把 info 也走 debug；带 "[debug] " 前缀的才是真 debug，丢弃以免刷屏。
        if not (isinstance(msg, str) and msg.startswith("[debug] ")):
            logger.debug("yt-dlp: %s", sanitize_diagnostic(msg))

    def info(self, msg):
        logger.debug("yt-dlp: %s", sanitize_diagnostic(msg))

    def warning(self, msg):
        logger.warning("yt-dlp: %s", sanitize_diagnostic(msg))

    def error(self, msg):
        logger.error("yt-dlp: %s", sanitize_diagnostic(msg))


_YDLP_LOGGER = _YDLPLogger()


# ── FFmpeg / FFprobe 绝对路径解析 ──────────────────────────────────────
# start.py 在启动时把内置二进制的绝对路径写入 AIT_FFMPEG / AIT_FFPROBE /
# AIT_FFMPEG_LOCATION（打包场景）。开发模式未设置时回退到系统 PATH。
# 显式用绝对路径，避免打包后（尤其 Windows）依赖 PATH 查找而 FileNotFoundError。
def _resolve_tool(env_key: str, name: str) -> str:
    p = os.environ.get(env_key)
    if p and Path(p).exists():
        return p
    return shutil.which(name) or name


FFMPEG_BIN = _resolve_tool("AIT_FFMPEG", "ffmpeg")
FFPROBE_BIN = _resolve_tool("AIT_FFPROBE", "ffprobe")


def _ffmpeg_location() -> str:
    """传给 yt-dlp 的 ffmpeg_location（目录或可执行文件路径均可）。无法确定时返回空。"""
    loc = os.environ.get("AIT_FFMPEG_LOCATION")
    if loc and Path(loc).exists():
        return loc
    if os.path.sep in FFMPEG_BIN and Path(FFMPEG_BIN).exists():
        return str(Path(FFMPEG_BIN).parent)
    return ""


def _subprocess_env() -> dict:
    """spawn 外部 ffmpeg/ffprobe 时清理 PyInstaller 注入的库路径。

    冻结环境会设置 DYLD_/LD_LIBRARY_PATH 指向 bundle 内的库，若让自带的静态
    ffmpeg 继承，可能加载到不兼容的 .dylib/.so。PyInstaller 官方建议：spawn
    系统/自带程序前，从 *_ORIG 还原原值，没有则删除该变量。
    """
    env = os.environ.copy()
    for var in ("DYLD_LIBRARY_PATH", "LD_LIBRARY_PATH"):
        orig = env.get(var + "_ORIG")
        if orig is not None:
            env[var] = orig
        else:
            env.pop(var, None)
    return env


def _run_media_proc(cmd: list[str], timeout: Optional[float] = None, label: str = "ffmpeg") -> str:
    """同步执行 ffmpeg/ffprobe（供 asyncio.to_thread 调用）。

    进程组 + 取消令牌登记（用户取消时 killpg 整组回收）+ 清理库路径 + 超时兜底。
    成功返回 stdout 文本；失败/超时/被取消时抛异常。
    """
    token = cancellation.current()
    popen_kwargs = {
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "text": True,
        "env": _subprocess_env(),
    }
    if os.name == "posix":
        popen_kwargs["start_new_session"] = True
    proc = subprocess.Popen(cmd, **popen_kwargs)
    if token is not None:
        token.register_process(proc)
    try:
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
            raise Exception(f"{label}超时（超过 {int(timeout or 0)} 秒）")
    finally:
        if token is not None:
            token.unregister_process(proc)
    if token is not None and token.is_cancelled():
        raise CancelledByUser()
    if proc.returncode != 0:
        raise Exception(f"{label}失败: {_media_stderr_summary(stderr)}")
    return stdout


def _media_stderr_summary(stderr: object) -> str:
    """抽取 ffmpeg/ffprobe 真正的失败原因，丢掉版本横幅和 configure 行。"""
    if isinstance(stderr, bytes):
        text = stderr.decode("utf-8", "replace")
    else:
        text = "" if stderr is None else str(stderr)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    skip_prefixes = (
        "ffmpeg version",
        "ffprobe version",
        "built with",
        "configuration:",
        "libavutil",
        "libavcodec",
        "libavformat",
        "libavdevice",
        "libavfilter",
        "libswscale",
        "libswresample",
        "libpostproc",
    )
    useful = [
        line
        for line in lines
        if not any(line.lower().startswith(prefix) for prefix in skip_prefixes)
    ]
    snippet = " | ".join((useful or lines)[-4:])
    return sanitize_diagnostic(snippet)


def _run_media_proc_bytes(cmd: list[str], timeout: Optional[float] = None, label: str = "ffmpeg") -> bytes:
    """同 _run_media_proc，但返回 *二进制* stdout（解码 PCM 等场景）。

    与文本版共用进程组登记 + 取消令牌 + 库路径清理 + 超时兜底，只是 stdout 走
    binary 管道，避免 text=True 把原始 PCM 字节按 UTF-8 解码而损坏。
    """
    token = cancellation.current()
    popen_kwargs = {
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "env": _subprocess_env(),
    }
    if os.name == "posix":
        popen_kwargs["start_new_session"] = True
    proc = subprocess.Popen(cmd, **popen_kwargs)
    if token is not None:
        token.register_process(proc)
    try:
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
            raise Exception(f"{label}超时（超过 {int(timeout or 0)} 秒）")
    finally:
        if token is not None:
            token.unregister_process(proc)
    if token is not None and token.is_cancelled():
        raise CancelledByUser()
    if proc.returncode != 0:
        raise Exception(f"{label}失败: {_media_stderr_summary(stderr)}")
    return stdout


# mlx-whisper 的解码输入：单声道、16kHz、float32 波形。
TRANSCRIBE_SAMPLE_RATE = 16000


def probe_duration(path: str, timeout: float = 60) -> float:
    """用 ffprobe 取媒体时长（秒）；无法解析时返回 0.0。"""
    out = _run_media_proc(
        [FFPROBE_BIN, "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", path],
        timeout=timeout, label="ffprobe 探测时长",
    ).strip()
    return float(out) if out else 0.0


def _pcm_from_wav_bytes(raw: bytes):
    """把 ffmpeg 输出的 PCM WAV 字节解析为 float32 单声道波形。"""
    import io
    import wave

    import numpy as np

    if not raw:
        raise Exception("ffmpeg 解码音频块失败: empty wav output")
    with wave.open(io.BytesIO(raw), "rb") as wf:
        if wf.getsampwidth() != 2:
            raise Exception(
                f"ffmpeg 解码音频块失败: expected 16-bit pcm, got {wf.getsampwidth() * 8}-bit"
            )
        channels = wf.getnchannels()
        frames = wf.readframes(wf.getnframes())
    samples = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1)
    return samples


def decode_audio_chunk(audio_path: str, start_s: float = 0.0, duration_s: Optional[float] = None):
    """解码 [start_s, start_s+duration_s) 区间的音频为 float32 numpy 波形。

    用绝对路径的 FFMPEG_BIN（不依赖 PATH，见项目约定）输出 16-bit PCM WAV，再归一化到
    [-1, 1] 的 float32——这正是 mlx_whisper.transcribe 接受的内存输入格式。
    输入侧 -ss/-t 做快速 seek，使逐块转录的内存只占单块大小（长音频友好）。
    duration_s 为 None 时解码到文件末尾（时长未知时的整段回退）。

    输出用 wav 而不是 raw ``s16le``：精简静态 FFmpeg 曾裁掉 raw PCM muxer，
    打包版会把完好音频误标成 unusable。wav muxer 是发行构建的必选项。
    """
    cmd = [FFMPEG_BIN, "-hide_banner", "-nostdin", "-v", "error", "-ss", f"{max(start_s, 0):.3f}"]
    if duration_s is not None:
        cmd += ["-t", f"{max(duration_s, 0):.3f}"]
    cmd += [
        "-i", audio_path,
        "-vn", "-threads", "0",
        "-f", "wav", "-ac", "1", "-acodec", "pcm_s16le",
        "-ar", str(TRANSCRIBE_SAMPLE_RATE), "-",
    ]
    raw = _run_media_proc_bytes(cmd, timeout=600, label="ffmpeg 解码音频块")
    return _pcm_from_wav_bytes(raw)


class VideoProcessor:
    """媒体处理器，使用yt-dlp下载和转换媒体"""

    def __init__(self):
        self.ydl_opts = {
            'format': 'bestaudio/best',  # 优先下载最佳音频源
            'outtmpl': '%(title)s.%(ext)s',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                # 直接在提取阶段转换为单声道 16k（空间小且稳定）
                'preferredcodec': 'm4a',
                'preferredquality': '192'
            }],
            # 全局FFmpeg参数：单声道 + 16k 采样率 + faststart
            'postprocessor_args': ['-ac', '1', '-ar', '16000', '-movflags', '+faststart'],
            'prefer_ffmpeg': True,
            'quiet': True,
            'no_warnings': True,
            'noplaylist': True,
            'socket_timeout': 30,
            'nocheckcertificate': True,
            'retries': 3,
        }
        # cookies 配置独立存储，供所有 yt-dlp 调用复用
        self._cookies_opts: dict = {}
        self._configure_cookies()

    def _get_base_opts(self, extra: dict = None) -> dict:
        """返回带 cookies 的基础 yt-dlp 选项，所有调用应从此获取。"""
        base = {
            'quiet': True,
            # 不再静默 warnings：格式回退、签名解算失败、后处理告警等都是排查的关键线索，
            # 经 _YDLP_LOGGER 写入日志文件（quiet=True 仍会抑制进度条，不刷屏）。
            'no_warnings': False,
            'noplaylist': True,
            # 探测阶段默认超时：10s 在国内慢网/代理下过于激进会误失败，放宽到 20s；
            # 下载阶段各平台适配器会用 get_download_opts 进一步覆盖（如 B站/抖音 60s）。
            'socket_timeout': 20,
            'extractor_retries': 2,
            'retries': 3,
            'nocheckcertificate': True,
            # 关键：把输出接到 Python logging，并彻底关掉进度条/颜色，
            # 避免 yt-dlp 写进程 stdout 管道导致并发下载时 Broken pipe。
            'logger': _YDLP_LOGGER,
            'noprogress': True,
            'no_color': True,
            'consoletitle': False,
            **self._cookies_opts,
            **(_REQUEST_COOKIE_OPTS.get() or {}),
        }
        # 显式指定 ffmpeg 位置：后处理（提取音频/合流/重封装）不再依赖 PATH，
        # 避免打包分发后找不到 ffmpeg 而后处理失败。
        ffmpeg_loc = _ffmpeg_location()
        if ffmpeg_loc:
            base['ffmpeg_location'] = ffmpeg_loc
        if extra:
            base.update(extra)
        return base

    def _get_extract_opts(self, url: str, extra: dict = None) -> dict:
        """返回媒体信息/字幕探测使用的 yt-dlp 选项。"""
        adapter = resolve_adapter(url)
        opts = self._get_base_opts()
        opts.update(adapter.get_extractor_args())
        if extra:
            opts.update(extra)
        return opts

    def _get_download_opts(self, url: str, extra: dict = None) -> dict:
        """返回实际下载使用的 yt-dlp 选项。

        下载参数从平台适配器获取，不同平台有不同的超时/重试策略。
        """
        adapter = resolve_adapter(url)
        opts = self._get_base_opts(adapter.get_download_opts())
        opts.update(adapter.get_extractor_args())
        if extra:
            opts.update(extra)
        return opts

    def _build_extraction_failure(
        self,
        url: str,
        stage: ExtractionStage,
        error: object,
        attempted_actions: list[ExtractionAction],
        *,
        kind: Optional[ExtractionFailureKind] = None,
    ) -> ExtractionFailure:
        """把原始异常一次性收敛成可持久化、可交给模型的脱敏现场。"""
        adapter = resolve_adapter(url)
        request_cookie_opts = _REQUEST_COOKIE_OPTS.get() or {}
        cookie_available = bool(self._cookies_opts or request_cookie_opts)
        deno_available = bool(shutil.which("deno"))
        extractor_opts = adapter.get_extractor_args()
        remote_components = extractor_opts.get("remote_components") or []
        ejs_configured = any(str(component).lower().startswith("ejs:") for component in remote_components)
        try:
            yt_dlp_version = getattr(yt_dlp.version, "__version__", None)
        except Exception:
            yt_dlp_version = None
        return ExtractionFailure.from_error(
            platform=adapter.name,
            stage=stage,
            error=error,
            kind=kind,
            yt_dlp_version=yt_dlp_version,
            cookie_available=cookie_available,
            deno_available=deno_available,
            ejs_available=ejs_configured and deno_available,
            attempted_actions=tuple(attempted_actions),
        )

    @staticmethod
    def _is_format_unavailable_error(exc: Exception) -> bool:
        """是否应在去掉 cookies 后重试。

        覆盖三类常见信号：
        - 取不到可用格式（多见于 YouTube 需解签名时）；
        - YouTube bot 验证（"Sign in to confirm you're not a bot"）；
        - 浏览器 cookies 读取/解密失败（App-Bound 加密、Keychain 拒绝等）——
          这类错误本就源于 cookies，去掉 cookies 重试往往能成功。
        """
        msg = str(exc)
        signals = (
            "Requested format is not available",
            "Only images are available",
            "Sign in to confirm",          # YouTube bot 验证
            "confirm you're not a bot",
            "could not find",              # cookies DB 路径/浏览器未找到
            "Failed to decrypt",           # Chrome App-Bound 加密
            "DPAPI",                       # Windows cookies 解密失败
            "unable to access",            # cookies 文件无权限
        )
        return any(s.lower() in msg.lower() for s in signals)

    @staticmethod
    def _without_cookie_opts(opts: dict) -> Optional[dict]:
        if "cookiefile" not in opts and "cookiesfrombrowser" not in opts:
            return None
        fallback = dict(opts)
        fallback.pop("cookiefile", None)
        fallback.pop("cookiesfrombrowser", None)
        return fallback

    async def _extract_info_with_cookie_fallback(
        self,
        url: str,
        opts: dict,
        timeout: float,
        attempted_actions: Optional[list[ExtractionAction]] = None,
    ) -> tuple[dict, dict]:
        import asyncio

        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = await asyncio.wait_for(
                    asyncio.to_thread(ydl.extract_info, url, False),
                    timeout=timeout,
                )
                return info, opts
        except Exception as e:
            fallback = self._without_cookie_opts(opts)
            if fallback and self._is_format_unavailable_error(e):
                if attempted_actions is not None:
                    attempted_actions.append(ExtractionAction.RETRY_WITHOUT_COOKIES)
                logger.warning(
                    "YouTube 可用格式为空，重试无 cookies 模式以启用 Android 客户端: %s",
                    sanitize_diagnostic(e),
                )
                with yt_dlp.YoutubeDL(fallback) as ydl:
                    info = await asyncio.wait_for(
                        asyncio.to_thread(ydl.extract_info, url, False),
                        timeout=timeout,
                    )
                    return info, fallback
            raise

    async def _download_with_cookie_fallback(
        self,
        url: str,
        opts: dict,
        timeout: float,
        label: str,
        attempted_actions: Optional[list[ExtractionAction]] = None,
    ) -> None:
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                await self._download_with_timeout(ydl, url, timeout, label)
        except Exception as e:
            fallback = self._without_cookie_opts(opts)
            if fallback and self._is_format_unavailable_error(e):
                if attempted_actions is not None:
                    attempted_actions.append(ExtractionAction.RETRY_WITHOUT_COOKIES)
                logger.warning(
                    "%s可用格式为空，重试无 cookies 模式以启用 Android 客户端: %s",
                    label,
                    sanitize_diagnostic(e),
                )
                with yt_dlp.YoutubeDL(fallback) as ydl:
                    await self._download_with_timeout(ydl, url, timeout, label)
                return
            raise

    @staticmethod
    async def _download_with_timeout(ydl, url: str, timeout: float, label: str = "下载"):
        """在线程池中执行 yt-dlp 下载并施加 wall-clock 兜底超时。

        注意：asyncio.wait_for 超时只能取消对协程的等待，无法终止 asyncio.to_thread
        启动的工作线程——底层下载会继续在后台运行。真正能让线程退出的是 yt-dlp 的
        socket_timeout（连接停滞时抛错使线程结束）。因此本超时仅作为兜底，并把
        空消息的 TimeoutError 转成可读错误。

        用户取消走 yt-dlp 官方机制：在 progress/postprocessor 钩子里 raise
        DownloadCancelled，yt-dlp 会捕获并干净中断下载阶段（详见 cancellation.py 决策记录）。
        所有下载调用都经过本函数，故只在此处集中注入钩子。
        """
        from yt_dlp.utils import DownloadCancelled

        token = cancellation.current()
        if token is not None:
            def _cancel_hook(_d):
                if token.is_cancelled():
                    raise DownloadCancelled("用户取消下载")
            ydl.add_progress_hook(_cancel_hook)
            try:
                ydl.add_postprocessor_hook(_cancel_hook)
            except AttributeError:
                pass  # 老版本 yt-dlp 无后处理钩子，下载阶段钩子已足够

        try:
            await asyncio.wait_for(
                asyncio.to_thread(ydl.download, [url]),
                timeout=timeout,
            )
        except DownloadCancelled:
            raise CancelledByUser()
        except asyncio.TimeoutError:
            raise Exception(
                f"{label}超时（超过 {int(timeout)} 秒）。文件可能过大或网络过慢；"
                "后台线程将在 socket_timeout 触发后自行结束。"
            )

    def use_auto_detect_browser_cookies(self, enabled: bool):
        """为当前 asyncio 任务临时启用浏览器 cookies 自动检测。"""
        opts = None
        if enabled and not self._cookies_opts:
            detected = self._detect_browser_cookies()
            if detected:
                opts = {"cookiesfrombrowser": (detected,)}
                logger.info("本次任务已获得浏览器 cookies 能力")
            else:
                logger.info("本次任务启用了浏览器 cookies 自动检测，但未找到可用浏览器 cookies")
        return _REQUEST_COOKIE_OPTS.set(opts)

    def browser_session_available(self) -> bool:
        """只暴露当前任务是否有不透明登录态能力，不暴露 Cookie 来源或内容。"""
        return bool(self._cookies_opts or (_REQUEST_COOKIE_OPTS.get() or {}))

    def recovery_profile_names(self, url: str) -> tuple[str, ...]:
        """返回当前平台允许的恢复 profile 名称，不暴露底层 yt-dlp 参数。"""
        return tuple(resolve_adapter(url).get_recovery_profiles())

    @staticmethod
    def reset_auto_detect_browser_cookies(token):
        _REQUEST_COOKIE_OPTS.reset(token)

    def _configure_cookies(self):
        """
        配置 yt-dlp cookies 以绕过 YouTube 反爬虫验证。
        优先级：COOKIES_FILE > COOKIES_BROWSER > 环境变量启用的自动检测。
        前端设置通过 use_auto_detect_browser_cookies() 按任务临时启用，不写入全局状态。
        """
        # 1) 显式 cookie 文件
        cookies_file = os.getenv("COOKIES_FILE")
        if cookies_file and os.path.isfile(cookies_file):
            self._cookies_opts['cookiefile'] = cookies_file
            self.ydl_opts['cookiefile'] = cookies_file
            logger.info("已配置 cookie 文件能力")
            return

        # 2) 环境变量指定浏览器
        browser = os.getenv("COOKIES_BROWSER", "").strip().lower()
        if browser:
            self._cookies_opts['cookiesfrombrowser'] = (browser,)
            self.ydl_opts['cookiesfrombrowser'] = (browser,)
            logger.info("已配置浏览器 cookies 能力")
            return

        # 3) 环境变量自动检测浏览器 cookies —— 默认关闭。
        # 普通用户应从前端设置显式打开；环境变量仅供开发/高级用户全局启用。
        auto_detect = os.getenv("AUTO_DETECT_BROWSER_COOKIES", "0").strip().lower()
        if auto_detect in {"1", "true", "yes", "on"}:
            detected = self._detect_browser_cookies()
            if detected:
                self._cookies_opts['cookiesfrombrowser'] = (detected,)
                self.ydl_opts['cookiesfrombrowser'] = (detected,)
                logger.info("已自动检测到浏览器 cookies 能力")
                return

        logger.info("未配置 cookies；如 YouTube 遇到反爬验证，请在设置中启用浏览器 cookies 自动检测，"
                    "或设置 COOKIES_FILE / COOKIES_BROWSER。")

    @staticmethod
    def _detect_browser_cookies() -> Optional[str]:
        """自动检测 macOS 上第一个可用的浏览器 cookie 数据库。"""
        candidates = [
            ("chrome", "~/Library/Application Support/Google/Chrome/Default/Cookies"),
            ("chrome", "~/Library/Application Support/Google/Chrome/Profile */Cookies"),
            ("brave", "~/Library/Application Support/BraveSoftware/Brave-Browser/Default/Cookies"),
            ("edge", "~/Library/Application Support/Microsoft Edge/Default/Cookies"),
            ("firefox", "~/Library/Application Support/Firefox/Profiles/*/cookies.sqlite"),
        ]
        import glob as _glob
        for browser_name, path_pattern in candidates:
            expanded = os.path.expanduser(path_pattern)
            matches = _glob.glob(expanded)
            if matches:
                return browser_name
        return None

    async def normalize_local_media_to_m4a(self, input_path: Path, output_dir: Path) -> str:
        """
        将本地上传的音视频转为单声道 16kHz AAC m4a，供 Faster-Whisper 使用（与 yt-dlp 后处理参数对齐）。
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        unique_id = str(uuid.uuid4())[:8]
        out_path = output_dir / f"upload_norm_{unique_id}.m4a"

        cmd = [
            FFMPEG_BIN, "-y", "-nostdin", "-i", str(input_path.resolve()),
            "-vn", "-ac", "1", "-ar", "16000",
            "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
            str(out_path.resolve()),
        ]

        def _run():
            _run_media_proc(cmd, label="FFmpeg 转换")
            if not out_path.exists():
                raise Exception("FFmpeg 未生成输出文件")

        await asyncio.to_thread(_run)
        return str(out_path)
    
    async def fetch_subtitles(self, url: str, output_dir: Path) -> SubtitleFetchResult:
        """先尝试取得字幕，并显式区分“确认缺席”和各阶段故障。"""
        import asyncio

        output_dir.mkdir(exist_ok=True)
        unique_id = str(uuid.uuid4())[:8]
        sub_dir = output_dir / f"subs_{unique_id}"
        attempted_actions: list[ExtractionAction] = []
        video_title: Optional[str] = None
        video_duration = 0.0
        current_stage = ExtractionStage.METADATA

        try:
            # 1. 快速探测：获取媒体信息和字幕可用性，不下载任何内容。
            attempted_actions.append(ExtractionAction.INSPECT_METADATA)
            try:
                check_opts = self._get_extract_opts(url)
                info, _ = await self._extract_info_with_cookie_fallback(
                    url, check_opts, 60.0, attempted_actions
                )
            except CancelledByUser:
                raise
            except Exception as exc:
                failure = self._build_extraction_failure(
                    url, ExtractionStage.METADATA, exc, attempted_actions
                )
                logger.warning("字幕元数据提取失败，将回退音频模式: %s", failure.sanitized_summary)
                return SubtitleFetchResult(status=SubtitleFetchStatus.FAILED, failure=failure)

            video_title = info.get("title", "unknown")
            raw_duration = info.get("duration") or 0
            parsed_duration = float(raw_duration)
            if not math.isfinite(parsed_duration) or parsed_duration < 0:
                raise ValueError("媒体时长无效")
            video_duration = parsed_duration
            manual_subs: dict = info.get("subtitles") or {}
            auto_caps: dict = info.get("automatic_captions") or {}

            # live_chat 不是语音字幕；只有过滤后两边都为空，才是“确认无字幕”。
            manual_langs = [key for key in manual_subs if not key.startswith("live_chat")]
            auto_langs = [key for key in auto_caps if not key.startswith("live_chat")]
            if not manual_langs and not auto_langs:
                logger.info("确认来源无可用字幕: %s", sanitize_source_reference(url))
                return SubtitleFetchResult(
                    status=SubtitleFetchStatus.NO_SUBTITLES,
                    title=video_title,
                    duration_seconds=video_duration,
                )

            prefer_manual = bool(manual_langs)
            candidate_langs = manual_langs if prefer_manual else auto_langs
            priority = resolve_adapter(url).get_subtitle_lang_priority()
            prefer_lang = next(
                (language for language in priority if language in candidate_langs),
                candidate_langs[0],
            )
            logger.info(
                "发现%s字幕，选用语言: %s（候选 %d 种）",
                "手动" if prefer_manual else "自动",
                prefer_lang,
                len(candidate_langs),
            )

            # 2. 仅下载字幕，跳过音视频。
            current_stage = ExtractionStage.SUBTITLE_DOWNLOAD
            attempted_actions.append(ExtractionAction.DOWNLOAD_SUBTITLE)
            sub_dir.mkdir(exist_ok=True)
            dl_opts = self._get_download_opts(url, {
                "writesubtitles": prefer_manual,
                "writeautomaticsub": not prefer_manual,
                "subtitlesformat": "vtt/srt/best",
                "subtitleslangs": [prefer_lang],
                "skip_download": True,
                "outtmpl": str(sub_dir / "sub.%(ext)s"),
            })
            try:
                await self._download_with_cookie_fallback(
                    url, dl_opts, 120.0, "下载字幕", attempted_actions
                )
            except CancelledByUser:
                raise
            except Exception as exc:
                failure = self._build_extraction_failure(
                    url, ExtractionStage.SUBTITLE_DOWNLOAD, exc, attempted_actions
                )
                logger.warning("字幕下载失败，将回退音频模式: %s", failure.sanitized_summary)
                return SubtitleFetchResult(
                    status=SubtitleFetchStatus.FAILED,
                    title=video_title,
                    duration_seconds=video_duration,
                    failure=failure,
                )

            sub_files = list(sub_dir.glob("*.vtt")) + list(sub_dir.glob("*.srt"))
            if not sub_files:
                failure = self._build_extraction_failure(
                    url,
                    ExtractionStage.SUBTITLE_DOWNLOAD,
                    "字幕下载动作完成但未生成字幕文件",
                    attempted_actions,
                    kind=ExtractionFailureKind.SUBTITLE_DOWNLOAD_FAILED,
                )
                logger.warning("字幕下载未产生文件，将回退音频模式")
                return SubtitleFetchResult(
                    status=SubtitleFetchStatus.FAILED,
                    title=video_title,
                    duration_seconds=video_duration,
                    failure=failure,
                )

            sub_file = sub_files[0]
            stem_parts = sub_file.stem.split(".")
            file_lang = stem_parts[-1] if len(stem_parts) > 1 else prefer_lang

            # 3. 解析失败与“没有字幕”不同：此时上游明确宣告过字幕存在。
            current_stage = ExtractionStage.SUBTITLE_PARSE
            attempted_actions.append(ExtractionAction.PARSE_SUBTITLE)
            try:
                if sub_file.suffix == ".vtt":
                    entries = await asyncio.to_thread(self._parse_vtt, str(sub_file))
                else:
                    entries = await asyncio.to_thread(self._parse_srt, str(sub_file))
                if not entries:
                    raise ValueError("字幕文件没有可用的文本条目")
            except CancelledByUser:
                raise
            except Exception as exc:
                failure = self._build_extraction_failure(
                    url,
                    ExtractionStage.SUBTITLE_PARSE,
                    exc,
                    attempted_actions,
                    kind=ExtractionFailureKind.SUBTITLE_PARSE_FAILED,
                )
                logger.warning("字幕解析失败，将回退音频模式: %s", failure.sanitized_summary)
                return SubtitleFetchResult(
                    status=SubtitleFetchStatus.FAILED,
                    title=video_title,
                    duration_seconds=video_duration,
                    failure=failure,
                )

            formatted = self._format_subtitle_entries(entries, file_lang)
            logger.info("字幕获取成功: lang=%s, %d 条目", file_lang, len(entries))
            return SubtitleFetchResult(
                status=SubtitleFetchStatus.FOUND,
                text=formatted,
                title=video_title,
                language=file_lang,
                duration_seconds=video_duration,
            )
        except CancelledByUser:
            raise
        except Exception as exc:
            # 防住上游返回畸形结构、适配器异常等边界；仍保持原有音频回退行为。
            failure = self._build_extraction_failure(
                url, current_stage, exc, attempted_actions
            )
            logger.warning("字幕路径异常，将回退音频模式: %s", failure.sanitized_summary)
            return SubtitleFetchResult(
                status=SubtitleFetchStatus.FAILED,
                title=video_title,
                duration_seconds=video_duration,
                failure=failure,
            )
        finally:
            if sub_dir.exists():
                try:
                    shutil.rmtree(str(sub_dir))
                except Exception:
                    pass

    # ------------------------------------------------------------------
    # 字幕解析辅助方法
    # ------------------------------------------------------------------

    def _parse_vtt(self, filepath: str) -> list:
        """解析 WebVTT 字幕文件，返回去重后的条目列表。

        特别处理 YouTube 自动字幕的「滚动追加」格式：
        同一句话会被分成多个 cue 逐字追加，只保留每组的「最终版本」。
        """
        raw_entries = []
        seen_texts: set = set()

        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()

        # 移除 WEBVTT 文件头，按空行分割 cue 块
        content = re.sub(r"^WEBVTT[^\n]*\n", "", content)
        blocks = re.split(r"\n{2,}", content.strip())

        for block in blocks:
            block = block.strip()
            if not block:
                continue

            lines = block.split("\n")
            timing_idx = next((i for i, l in enumerate(lines) if "-->" in l), -1)
            if timing_idx < 0:
                continue

            timing_line = lines[timing_idx]
            text_lines = lines[timing_idx + 1:]

            match = re.match(
                r"(\d{1,2}:\d{2}(?::\d{2})?(?:[.,]\d+)?)\s*-->\s*"
                r"(\d{1,2}:\d{2}(?::\d{2})?(?:[.,]\d+)?)",
                timing_line,
            )
            if not match:
                continue

            start_str = self._normalize_time(match.group(1))
            end_str = self._normalize_time(match.group(2))

            raw_text = " ".join(text_lines)
            # 去除 HTML / VTT 内联标签（包括 YouTube 逐字时间码标签）
            text = re.sub(r"<[^>]+>", "", raw_text)
            text = (
                text.replace("&amp;", "&")
                    .replace("&lt;", "<")
                    .replace("&gt;", ">")
                    .replace("&nbsp;", " ")
                    .replace("&#39;", "'")
                    .replace("&quot;", '"')
                    .strip()
            )
            # 合并行内多余空白
            text = re.sub(r"\s+", " ", text).strip()

            if not text or text in seen_texts:
                continue

            seen_texts.add(text)
            raw_entries.append({"start": start_str, "end": end_str, "text": text})

        # ── 二次去重：过滤 YouTube「滚动追加」的中间状态 ──────────────────
        # 若条目 i 的文本是条目 i+1 文本的起始子串，则条目 i 是中间状态，丢弃。
        # 同时丢弃纯空白/单字符的噪音条目。
        if not raw_entries:
            return []

        entries = []
        for i, entry in enumerate(raw_entries):
            text = entry["text"]
            if len(text) < 2:
                continue
            # 检查后续若干条是否以当前文本开头（滚动追加的特征）
            is_intermediate = False
            for j in range(i + 1, min(i + 4, len(raw_entries))):
                next_text = raw_entries[j]["text"]
                if next_text.startswith(text) and len(next_text) > len(text):
                    is_intermediate = True
                    break
            if not is_intermediate:
                entries.append(entry)

        return entries

    def _parse_srt(self, filepath: str) -> list:
        """解析 SRT 字幕文件，返回去重后的条目列表。"""
        entries = []
        seen_texts: set = set()

        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()

        blocks = re.split(r"\n{2,}", content.strip())

        for block in blocks:
            lines = block.strip().split("\n")
            timing_idx = next((i for i, l in enumerate(lines) if "-->" in l), -1)
            if timing_idx < 0:
                continue

            timing_line = lines[timing_idx]
            text_lines = lines[timing_idx + 1:]

            match = re.match(
                r"(\d{1,2}:\d{2}:\d{2}[.,]\d+)\s*-->\s*(\d{1,2}:\d{2}:\d{2}[.,]\d+)",
                timing_line,
            )
            if not match:
                continue

            start_str = self._normalize_time(match.group(1))
            end_str = self._normalize_time(match.group(2))

            text = " ".join(text_lines)
            text = re.sub(r"<[^>]+>", "", text).strip()

            if not text or text in seen_texts:
                continue

            seen_texts.add(text)
            entries.append({"start": start_str, "end": end_str, "text": text})

        return entries

    def _normalize_time(self, time_str: str) -> str:
        """将 HH:MM:SS.mmm 或 MM:SS.mmm 统一转为 MM:SS 格式。"""
        time_str = re.sub(r"[.,]\d+$", "", time_str)
        parts = time_str.split(":")
        if len(parts) == 3:
            h, m, s = int(parts[0]), int(parts[1]), int(parts[2])
            return f"{h * 60 + m:02d}:{s:02d}"
        elif len(parts) == 2:
            m, s = int(parts[0]), int(parts[1])
            return f"{m:02d}:{s:02d}"
        return time_str

    def _format_subtitle_entries(self, entries: list, language: str) -> str:
        """将字幕条目格式化为与 Whisper 输出兼容的 Markdown，供下游管道直接使用。"""
        lines = [
            "# Video Transcription",
            "",
            f"**Detected Language:** {language}",
            "**Language Probability:** 1.00",
            "",
            "## Transcription Content",
            "",
        ]
        for entry in entries:
            lines.append(f"**[{entry['start']} - {entry['end']}]**")
            lines.append("")
            lines.append(entry["text"])
            lines.append("")
        return "\n".join(lines)

    async def download_and_convert(
        self,
        url: str,
        output_dir: Path,
        prefetched_title: Optional[str] = None,
        prefetched_duration: float = 0,
        previous_actions: tuple[ExtractionAction, ...] = (),
        recovery_profile: Optional[str] = None,
    ) -> tuple[str, str]:
        """
        下载媒体并提取音频为m4a格式。

        prefetched_title: 若调用方已通过 fetch_subtitles 探测过媒体信息，
        可直接传入，跳过重复的 extract_info 网络请求。
        """
        attempted_actions = list(previous_actions)
        failure_stage = ExtractionStage.MEDIA_DOWNLOAD
        try:
            import asyncio

            # 创建输出目录
            output_dir.mkdir(exist_ok=True)
            
            # 生成唯一的文件名
            unique_id = str(uuid.uuid4())[:8]
            output_template = str(output_dir / f"audio_{unique_id}.%(ext)s")
            
            # 更新yt-dlp选项
            ydl_opts = self._get_download_opts(url, {
                'format': 'bestaudio/best',
                'outtmpl': output_template,
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'm4a',
                    'preferredquality': '192'
                }],
                'postprocessor_args': ['-ac', '1', '-ar', '16000', '-movflags', '+faststart'],
                'prefer_ffmpeg': True,
            })
            if recovery_profile is not None:
                profile = resolve_adapter(url).get_recovery_profiles().get(recovery_profile)
                if profile is None:
                    raise ValueError("未允许的媒体恢复 profile")
                ydl_opts.update(profile.get("options") or {})
                if not profile.get("use_cookies", False):
                    ydl_opts = self._without_cookie_opts(ydl_opts) or ydl_opts
                elif not self.browser_session_available():
                    raise ValueError("该恢复 profile 需要已获准的浏览器会话")
            
            logger.info("开始下载音频来源: %s", sanitize_source_reference(url))
            
            active_opts = ydl_opts
            if prefetched_title:
                # fetch_subtitles 已探测过，直接下载不重复 extract_info
                video_title = prefetched_title
                expected_duration = prefetched_duration
                logger.info(
                    "复用预取标题: %s, 时长≈%ds",
                    sanitize_diagnostic(video_title, max_length=160),
                    int(expected_duration),
                )
            else:
                # 获取媒体信息（放到线程池避免阻塞事件循环，超时 60s）
                failure_stage = ExtractionStage.METADATA
                attempted_actions.append(ExtractionAction.INSPECT_METADATA)
                info, active_opts = await self._extract_info_with_cookie_fallback(
                    url, ydl_opts, 60.0, attempted_actions
                )
                video_title = info.get('title', 'unknown')
                expected_duration = info.get('duration') or 0
                logger.info("已取得媒体标题: %s", sanitize_diagnostic(video_title, max_length=160))
            
            # 播客等大文件（100MB+）在慢速连接下可能远超 5 分钟，
            # 给足兜底时间，避免合法但缓慢的下载被硬超时误杀。
            failure_stage = ExtractionStage.MEDIA_DOWNLOAD
            attempted_actions.append(ExtractionAction.DOWNLOAD_AUDIO)
            await self._download_with_cookie_fallback(
                url, active_opts, 1800.0, "下载", attempted_actions
            )

            failure_stage = ExtractionStage.MEDIA_VALIDATION
            attempted_actions.append(ExtractionAction.VALIDATE_MEDIA)
            
            # 查找生成的m4a文件
            audio_file = str(output_dir / f"audio_{unique_id}.m4a")
            
            if not os.path.exists(audio_file):
                # 如果m4a文件不存在，查找其他音频格式
                for ext in ['webm', 'mp4', 'mp3', 'wav']:
                    potential_file = str(output_dir / f"audio_{unique_id}.{ext}")
                    if os.path.exists(potential_file):
                        audio_file = potential_file
                        break
                else:
                    raise Exception("未找到下载的音频文件")
            
            # 校验时长，如果和源文件差异较大，尝试一次ffmpeg规范化重封装。
            # 用绝对路径的 ffprobe/ffmpeg + 进程组（可取消）+ 无 shell，修掉两个隐患：
            #  · 打包后若无 ffprobe，旧实现会静默吞异常令校验失效，损坏/截断音频被
            #    直送 Whisper（现已随包内置 ffprobe，探测失败也会显式告警）；
            #  · shell=True 的跨平台/引号问题，且子进程无法被取消令牌回收。
            def _probe_duration(path: str) -> float:
                return probe_duration(path)

            try:
                actual_duration = await asyncio.to_thread(_probe_duration, audio_file)
            except Exception as _e:
                logger.warning(
                    "ffprobe 时长探测失败（跳过时长校验）: %s",
                    sanitize_diagnostic(_e),
                )
                actual_duration = 0.0

            if expected_duration and actual_duration and abs(actual_duration - expected_duration) / expected_duration > 0.1:
                logger.warning(
                    f"音频时长异常，期望{expected_duration}s，实际{actual_duration}s，尝试重封装修复…"
                )
                try:
                    fixed_path = str(output_dir / f"audio_{unique_id}_fixed.m4a")

                    def _fix_and_probe() -> float:
                        _run_media_proc(
                            [FFMPEG_BIN, "-y", "-nostdin", "-i", audio_file, "-vn",
                             "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", fixed_path],
                            timeout=600, label="ffmpeg 重封装",
                        )
                        return _probe_duration(fixed_path)

                    actual_duration2 = await asyncio.to_thread(_fix_and_probe)
                    audio_file = fixed_path
                    logger.info(f"重封装完成，新时长≈{actual_duration2:.2f}s")
                except Exception as e:
                    logger.error("重封装失败：%s", sanitize_diagnostic(e))
            
            logger.info("音频文件已保存: %s", sanitize_diagnostic(audio_file, max_length=200))
            return audio_file, video_title

        except CancelledByUser:
            raise
        except MediaExtractionError:
            raise
        except Exception as e:
            failure = self._build_extraction_failure(
                url, failure_stage, e, attempted_actions
            )
            logger.error("媒体获取失败: %s", failure.sanitized_summary)
            raise MediaExtractionError(failure) from None

    def get_video_info(self, url: str) -> dict:
        """获取媒体信息"""
        try:
            with yt_dlp.YoutubeDL(self._get_extract_opts(url)) as ydl:
                info = ydl.extract_info(url, download=False)
                return {
                    'title': info.get('title', ''),
                    'duration': info.get('duration', 0),
                    'uploader': info.get('uploader', ''),
                    'upload_date': info.get('upload_date', ''),
                    'description': info.get('description', ''),
                    'view_count': info.get('view_count', 0),
                }
        except Exception as e:
            safe_error = sanitize_diagnostic(e)
            logger.error("获取媒体信息失败: %s", safe_error)
            raise Exception(f"获取媒体信息失败: {safe_error}") from None

    async def get_video_title(self, url: str) -> str:
        """快速获取标题（仅探测，不下载）"""
        try:
            import asyncio
            check_opts = self._get_extract_opts(url)
            info, _ = await self._extract_info_with_cookie_fallback(url, check_opts, 45.0)
            return info.get("title", "unknown")
        except Exception as e:
            logger.error("获取标题失败: %s", sanitize_diagnostic(e))
            return "unknown"

    async def get_video_formats(self, url: str) -> dict:
        """获取媒体可用格式及字幕信息（用于下载选择）。
        
        Returns:
            {
                "video_formats": [...],
                "audio_formats": [...],
                "subtitles": {"manual": [...], "auto": [...]},
                "title": str,
                "duration": int,
            }
        """
        try:
            import asyncio
            check_opts = self._get_extract_opts(url)
            info, _ = await self._extract_info_with_cookie_fallback(url, check_opts, 60.0)

            video_formats = []
            audio_formats = []
            # 按用户可见特征去重：(height, vcodec, ext) / (abr, acodec, ext)
            seen_v = {}  # key -> index in video_formats
            seen_a = {}  # key -> index in audio_formats

            # ── 视频格式 ────────────────────────────────────
            video_formats.append({
                "id": "bestvideo+bestaudio/best",
                "ext": "mp4",
                "resolution": "",
                "note": "best",
                "filesize": 0,
                "vcodec": "",
                "acodec": "",
                "type": "video",
            })

            for f in info.get("formats", []):
                fid = f.get("format_id", "")
                ext = f.get("ext", "")
                vcodec = f.get("vcodec", "none")
                acodec = f.get("acodec", "none")
                has_video = vcodec and vcodec != "none"
                has_audio = acodec and acodec != "none"

                # 视频格式（有视频轨道）
                if has_video:
                    height = f.get("height") or 0
                    # 去重 key：同分辨率 + 同视频编码 + 同容器 = 重复
                    vkey = (height, vcodec, ext)

                    resolution = f.get("resolution") or f.get("format_note") or ""
                    filesize = f.get("filesize") or f.get("filesize_approx") or 0
                    fps = f.get("fps") or 0

                    # 优先保留含音频的格式，其次保留 filesize 更大的（通常质量更好）
                    if vkey in seen_v:
                        existing_idx = seen_v[vkey]
                        existing = video_formats[existing_idx]
                        existing_has_audio = bool(existing.get("acodec"))
                        current_has_audio = has_audio
                        if (not existing_has_audio and current_has_audio) or \
                           (existing_has_audio == current_has_audio and filesize > existing.get("filesize", 0)):
                            # 用当前条目替换
                            pass  # fall through to update below
                        else:
                            continue  # 保留原有

                    label_parts = [resolution]
                    if ext:
                        label_parts.append(f"({ext})")
                    if vcodec:
                        label_parts.append(f"[{vcodec}]")
                    if fps:
                        label_parts.append(f"{fps}fps")

                    entry = {
                        "id": _download_format_id(fid, has_audio),
                        "ext": ext,
                        "resolution": resolution,
                        "height": height,
                        "fps": fps,
                        "note": " ".join(label_parts),
                        "filesize": filesize,
                        "vcodec": vcodec,
                        "acodec": acodec if has_audio else "",
                        "type": "video",
                    }

                    if vkey in seen_v:
                        video_formats[seen_v[vkey]] = entry
                    else:
                        seen_v[vkey] = len(video_formats)
                        video_formats.append(entry)

                # 纯音频格式
                if not has_video and has_audio:
                    abr = f.get("abr") or 0
                    asr = f.get("asr") or 0
                    # 去重 key：同码率 + 同编码 + 同容器 = 重复
                    akey = (abr, acodec, ext)

                    filesize = f.get("filesize") or f.get("filesize_approx") or 0
                    format_note = f.get("format_note") or ""

                    if akey in seen_a:
                        existing_idx = seen_a[akey]
                        existing = audio_formats[existing_idx]
                        # 保留采样率更高的，或 filesize 更大的
                        existing_asr = existing.get("asr", 0) or 0
                        if asr > existing_asr or (asr == existing_asr and filesize > existing.get("filesize", 0)):
                            pass  # replace
                        else:
                            continue

                    label_parts = [format_note] if format_note else []
                    if ext:
                        label_parts.append(f"({ext})")
                    if acodec:
                        label_parts.append(f"[{acodec}]")
                    if abr:
                        label_parts.append(f"~{abr}kbps")
                    if asr:
                        label_parts.append(f"{int(asr)}Hz")

                    entry = {
                        "id": fid,
                        "ext": ext,
                        "abr": abr,
                        "asr": asr,
                        "note": " ".join(label_parts) or fid,
                        "filesize": filesize,
                        "acodec": acodec,
                        "type": "audio",
                    }

                    if akey in seen_a:
                        audio_formats[seen_a[akey]] = entry
                    else:
                        seen_a[akey] = len(audio_formats)
                        audio_formats.append(entry)

            # 排序：视频按分辨率降序，音频按码率降序
            video_formats[1:] = sorted(video_formats[1:], key=lambda x: -(x.get("height", 0)))
            audio_formats.sort(key=lambda x: -(x.get("abr", 0)))

            # 添加默认音频选项
            if audio_formats:
                audio_formats.insert(0, {
                    "id": "bestaudio/best",
                    "ext": "m4a",
                    "abr": 0,
                    "asr": 0,
                    "note": "best",
                    "filesize": 0,
                    "acodec": "",
                    "type": "audio",
                })

            # ── 字幕信息 ──────────────────────────────────────
            manual_subs_raw = info.get("subtitles") or {}
            auto_caps_raw = info.get("automatic_captions") or {}
            manual_langs = sorted([k for k in manual_subs_raw if not k.startswith("live_chat")])
            auto_langs = sorted([k for k in auto_caps_raw if not k.startswith("live_chat")])

            subtitles = {
                "manual": manual_langs,
                "auto": auto_langs,
            }

            return {
                "video_formats": video_formats[:30],
                "audio_formats": audio_formats[:20],
                "subtitles": subtitles,
                "title": info.get("title", ""),
                "duration": info.get("duration") or 0,
            }

        except Exception as e:
            safe_error = sanitize_diagnostic(e)
            logger.error("获取媒体格式失败: %s", safe_error)
            raise Exception(f"获取媒体格式失败: {safe_error}") from None

    async def download_video_only(
        self, url: str, output_dir: Path, format_id: str = "best", filename_base: str = ""
    ) -> str:
        """仅下载媒体文件（不转录），返回输出路径"""
        try:
            import asyncio
            output_dir.mkdir(exist_ok=True)

            unique_id = str(uuid.uuid4())[:8]
            safe_name = self._sanitize_filename(filename_base) if filename_base else f"video_{unique_id}"
            output_template = str(output_dir / f"{safe_name}.%(ext)s")

            logger.info(
                "开始下载: %s (format=%s)",
                sanitize_source_reference(url),
                sanitize_diagnostic(format_id, max_length=80),
            )

            # 默认合成 mp4；若该来源的音视频编码与 mp4 容器不兼容（合流/重封装报错，
            # 内置精简版 ffmpeg 又无对应转码器），回退到几乎万能的 mkv 容器重试一次。
            async def _try_download(container: str):
                opts = self._get_download_opts(url, {
                    "format": format_id,
                    "outtmpl": output_template,
                    "merge_output_format": container,
                })
                await self._download_with_cookie_fallback(url, opts, 1800.0, "下载")

            try:
                await _try_download("mp4")
            except Exception as e:
                msg = str(e).lower()
                if any(s in msg for s in ("postprocessing", "merge", "remux", "invalid argument", "not in a format")):
                    logger.warning("mp4 合成失败，回退 mkv 容器重试: %s", sanitize_diagnostic(e))
                    await _try_download("mkv")
                else:
                    raise

            # 查找输出文件
            import glob
            pattern = str(output_dir / f"{safe_name}.*")
            candidates = glob.glob(pattern)
            if candidates:
                return candidates[0]

            # 回退：尝试以unique_id查找
            fallback_pattern = str(output_dir / f"*{unique_id}*")
            candidates = glob.glob(fallback_pattern)
            if candidates:
                return candidates[0]

            raise Exception("下载完成但未找到输出文件")

        except Exception as e:
            safe_error = sanitize_diagnostic(e)
            logger.error("下载失败: %s", safe_error)
            raise Exception(f"下载失败: {safe_error}") from None

    async def download_audio_only(
        self, url: str, output_dir: Path, format_id: str = "bestaudio/best",
        filename_base: str = "", audio_format: str = "m4a"
    ) -> str:
        """仅下载音频文件，返回输出路径。"""
        try:
            import asyncio
            output_dir.mkdir(exist_ok=True)

            unique_id = str(uuid.uuid4())[:8]
            safe_name = self._sanitize_filename(filename_base) if filename_base else f"audio_{unique_id}"
            output_template = str(output_dir / f"{safe_name}.%(ext)s")

            dl_opts = self._get_download_opts(url, {
                "format": format_id,
                "outtmpl": output_template,
                "merge_output_format": audio_format,
                "postprocessors": [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": audio_format,
                }] if audio_format not in ("m4a", "mp3", "opus", "aac", "flac", "wav") else [],
            })

            logger.info(
                "开始下载音频: %s (format=%s)",
                sanitize_source_reference(url),
                sanitize_diagnostic(format_id, max_length=80),
            )

            await self._download_with_cookie_fallback(url, dl_opts, 1800.0, "下载音频")

            # 查找输出文件（download_audio_only）
            import glob as _glob
            pattern = str(output_dir / f"{safe_name}.*")
            candidates = _glob.glob(pattern)
            if candidates:
                return candidates[0]

            fallback_pattern = str(output_dir / f"*{unique_id}*")
            candidates = _glob.glob(fallback_pattern)
            if candidates:
                return candidates[0]

            raise Exception("下载完成但未找到音频文件")

        except Exception as e:
            safe_error = sanitize_diagnostic(e)
            logger.error("下载音频失败: %s", safe_error)
            raise Exception(f"下载音频失败: {safe_error}") from None

    async def download_subtitles_file(
        self, url: str, output_dir: Path, lang: str = "en",
        filename_base: str = ""
    ) -> tuple[str, str]:
        """仅下载字幕文件，返回 (文件路径, 语言代码)。"""
        try:
            import asyncio
            output_dir.mkdir(exist_ok=True)

            # 先探测字幕可用性
            check_opts = self._get_extract_opts(url)
            info, _ = await self._extract_info_with_cookie_fallback(url, check_opts, 60.0)

            manual_subs = info.get("subtitles") or {}
            auto_caps = info.get("automatic_captions") or {}
            manual_langs = [k for k in manual_subs if not k.startswith("live_chat")]
            auto_langs = [k for k in auto_caps if not k.startswith("live_chat")]

            prefer_manual = bool(manual_langs)
            candidate_langs = manual_langs if prefer_manual else auto_langs

            if not candidate_langs:
                raise Exception("无可用字幕")

            # 选语言：指定语言 > 英语 > 中文 > 第一个可用
            _priority = [lang, "en", "en-orig", "zh-Hans", "zh-Hant", "zh"]
            chosen_lang = next(
                (l for l in _priority if l in candidate_langs),
                candidate_langs[0],
            )

            unique_id = str(uuid.uuid4())[:8]
            safe_name = self._sanitize_filename(filename_base) if filename_base else f"subs_{unique_id}"
            safe_name_no_ext = safe_name.rsplit(".", 1)[0] if "." in safe_name else safe_name
            output_template = str(output_dir / f"{safe_name_no_ext}.%(ext)s")

            dl_opts = self._get_download_opts(url, {
                "writesubtitles": prefer_manual,
                "writeautomaticsub": not prefer_manual,
                "subtitlesformat": "vtt/srt/best",
                "subtitleslangs": [chosen_lang],
                "skip_download": True,
                "outtmpl": output_template,
            })

            # 下载字幕文件，体积小，给较短兜底超时
            await self._download_with_cookie_fallback(url, dl_opts, 120.0, "下载字幕")

            # 查找输出文件（download_subtitles_file）
            import glob as _glob
            pattern_no_ext = str(output_dir / f"{safe_name_no_ext}.*")
            candidates = _glob.glob(pattern_no_ext)
            # 过滤出字幕格式
            sub_exts = {".vtt", ".srt"}
            sub_files = [c for c in candidates if Path(c).suffix.lower() in sub_exts]
            if sub_files:
                return sub_files[0], chosen_lang

            # 回退：按 unique_id 查找
            fallback = _glob.glob(str(output_dir / f"*{unique_id}*"))
            sub_files = [c for c in fallback if Path(c).suffix.lower() in sub_exts]
            if sub_files:
                return sub_files[0], chosen_lang

            raise Exception("字幕下载完成但未找到文件")

        except Exception as e:
            safe_error = sanitize_diagnostic(e)
            logger.error("下载字幕失败: %s", safe_error)
            raise Exception(f"下载字幕失败: {safe_error}") from None

    @staticmethod
    def _sanitize_filename(name: str) -> str:
        """安全化文件名"""
        name = re.sub(r'[<>:"/\\|?*]', "_", name)
        name = re.sub(r"\s+", "_", name).strip("._ ")
        return name[:100] or "video"
