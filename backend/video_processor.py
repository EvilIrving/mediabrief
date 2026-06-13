import os
import re
import shutil
import uuid
import asyncio
import subprocess
import yt_dlp
import logging
from pathlib import Path
from typing import Optional

import cancellation
from cancellation import CancelledByUser

logger = logging.getLogger(__name__)


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
            logger.debug("yt-dlp: %s", msg)

    def info(self, msg):
        logger.debug("yt-dlp: %s", msg)

    def warning(self, msg):
        logger.warning("yt-dlp: %s", msg)

    def error(self, msg):
        logger.error("yt-dlp: %s", msg)


_YDLP_LOGGER = _YDLPLogger()


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
            'no_warnings': True,
            'noplaylist': True,
            'socket_timeout': 10,
            'extractor_retries': 1,
            'retries': 3,
            'nocheckcertificate': True,
            # 关键：把输出接到 Python logging，并彻底关掉进度条/颜色，
            # 避免 yt-dlp 写进程 stdout 管道导致并发下载时 Broken pipe。
            'logger': _YDLP_LOGGER,
            'noprogress': True,
            'no_color': True,
            'consoletitle': False,
            **self._cookies_opts,
        }
        if extra:
            base.update(extra)
        return base

    @staticmethod
    def _is_bilibili_url(url: str) -> bool:
        return bool(re.search(r"(^|://)(www\.)?bilibili\.com/|(^|://)b23\.tv/", url or "", re.I))

    @staticmethod
    def _is_youtube_url(url: str) -> bool:
        return bool(re.search(r"(^|://|\.)(youtube\.com|youtu\.be)/", url or "", re.I))

    def _youtube_js_opts(self, url: str) -> dict:
        """YouTube 专用：启用 EJS 远程组件解 nsig 签名。

        该组件需从 GitHub 拉取，对网络受限（如国内访问 GitHub 不稳）的用户可能
        在下载途中触发 BrokenPipe。它仅对 YouTube 有意义，故非 YouTube 链接一律
        不启用，避免无谓地引入 GitHub 依赖与失败面（如 B站 下载时的 broken pipe）。
        """
        return {"remote_components": ["ejs:github"]} if self._is_youtube_url(url) else {}

    def _get_download_opts(self, url: str, extra: dict = None) -> dict:
        """返回实际下载使用的 yt-dlp 选项；慢速站点可在这里放宽网络容忍度。"""
        opts = self._get_base_opts({
            "socket_timeout": 30,
            "retries": 3,
            "fragment_retries": 3,
            "file_access_retries": 3,
        })
        if self._is_bilibili_url(url):
            opts.update({
                "socket_timeout": 60,
                "retries": 10,
                "fragment_retries": 10,
                "file_access_retries": 5,
                "http_chunk_size": 10 * 1024 * 1024,
            })
        if extra:
            opts.update(extra)
        return opts

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

    def _configure_cookies(self):
        """
        配置 yt-dlp cookies 以绕过 YouTube 反爬虫验证。
        优先级：COOKIES_FILE > COOKIES_BROWSER > 自动检测本地浏览器
        """
        # 1) 显式 cookie 文件
        cookies_file = os.getenv("COOKIES_FILE")
        if cookies_file and os.path.isfile(cookies_file):
            self._cookies_opts['cookiefile'] = cookies_file
            self.ydl_opts['cookiefile'] = cookies_file
            logger.info(f"使用 cookie 文件: {cookies_file}")
            return

        # 2) 环境变量指定浏览器
        browser = os.getenv("COOKIES_BROWSER", "").strip().lower()
        if browser:
            self._cookies_opts['cookiesfrombrowser'] = (browser,)
            self.ydl_opts['cookiesfrombrowser'] = (browser,)
            logger.info(f"使用浏览器 cookies: {browser}")
            return

        # 3) 自动检测浏览器 cookies，默认开启以绕过 YouTube 反爬验证
        auto_detect = os.getenv("AUTO_DETECT_BROWSER_COOKIES", "1").strip().lower()
        if auto_detect not in {"0", "false", "no", "off"}:
            detected = self._detect_browser_cookies()
            if detected:
                self._cookies_opts['cookiesfrombrowser'] = (detected,)
                self.ydl_opts['cookiesfrombrowser'] = (detected,)
                logger.info(f"自动检测浏览器 cookies: {detected}")
                return

        logger.info("未配置 cookies；如 YouTube 遇到反爬验证，请设置 COOKIES_FILE、COOKIES_BROWSER，"
                    "或设置 AUTO_DETECT_BROWSER_COOKIES=1 启用自动检测。")

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
            "ffmpeg", "-y", "-nostdin", "-i", str(input_path.resolve()),
            "-vn", "-ac", "1", "-ar", "16000",
            "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
            str(out_path.resolve()),
        ]

        token = cancellation.current()

        def _run():
            # 用 Popen + start_new_session 让 ffmpeg 成为进程组组长，登记到取消令牌；
            # 用户取消时 killpg 整组回收。subprocess.run 起的进程拿不到句柄、杀不掉。
            popen_kwargs = {"stdout": subprocess.PIPE, "stderr": subprocess.PIPE, "text": True}
            if os.name == "posix":
                popen_kwargs["start_new_session"] = True
            proc = subprocess.Popen(cmd, **popen_kwargs)
            if token is not None:
                token.register_process(proc)
            try:
                _, stderr = proc.communicate()
            finally:
                if token is not None:
                    token.unregister_process(proc)
            if token is not None and token.is_cancelled():
                raise CancelledByUser()
            if proc.returncode != 0:
                err = (stderr or "").strip()
                raise Exception(f"FFmpeg 转换失败: {err[:800]}")
            if not out_path.exists():
                raise Exception("FFmpeg 未生成输出文件")

        await asyncio.to_thread(_run)
        return str(out_path)
    
    async def fetch_subtitles(self, url: str, output_dir: Path) -> tuple[Optional[str], Optional[str], Optional[str], float]:
        """
        先尝试从平台获取字幕文本，比下载音频快得多。

        Returns:
            (subtitle_markdown, video_title, language_code, duration)
            subtitle_markdown 为 None 表示无可用字幕。
        """
        import asyncio

        output_dir.mkdir(exist_ok=True)
        unique_id = str(uuid.uuid4())[:8]
        sub_dir = output_dir / f"subs_{unique_id}"

        try:
            # 1. 快速探测：获取媒体信息和字幕可用性，不下载任何内容
            check_opts = self._get_base_opts()
            with yt_dlp.YoutubeDL(check_opts) as ydl:
                info = await asyncio.wait_for(
                    asyncio.to_thread(ydl.extract_info, url, False),
                    timeout=60.0,
                )

            video_title = info.get("title", "unknown")
            video_duration = info.get("duration") or 0
            manual_subs: dict = info.get("subtitles") or {}
            auto_caps: dict = info.get("automatic_captions") or {}

            # 过滤掉 live_chat 等非语音轨道
            manual_langs = [k for k in manual_subs if not k.startswith("live_chat")]
            auto_langs = [k for k in auto_caps if not k.startswith("live_chat")]

            if not manual_langs and not auto_langs:
                logger.info(f"无可用字幕: {url}")
                return None, video_title, None, video_duration

            # 优先手动字幕，其次自动字幕
            prefer_manual = bool(manual_langs)
            candidate_langs = manual_langs if prefer_manual else auto_langs

            # 按优先级选语言：英语 > 简体中文 > 繁体中文 > 其他（取第一个）
            _priority = ["en", "en-orig", "zh-Hans", "zh-Hant", "zh", "ja", "ko", "fr", "de", "es"]
            prefer_lang = next(
                (lang for lang in _priority if lang in candidate_langs),
                candidate_langs[0],
            )
            logger.info(
                f"发现{'手动' if prefer_manual else '自动'}字幕，选用语言: {prefer_lang}"
                f"（候选 {len(candidate_langs)} 种）"
            )

            # 2. 仅下载字幕，跳过音视频
            sub_dir.mkdir(exist_ok=True)
            dl_opts = self._get_base_opts({
                "writesubtitles": prefer_manual,
                "writeautomaticsub": not prefer_manual,
                "subtitlesformat": "vtt/srt/best",
                "subtitleslangs": [prefer_lang],
                "skip_download": True,
                "outtmpl": str(sub_dir / "sub.%(ext)s"),
            })
            with yt_dlp.YoutubeDL(dl_opts) as ydl:
                # 仅下载字幕文件，体积小，给较短兜底超时
                await self._download_with_timeout(ydl, url, 120.0, "下载字幕")

            # 3. 查找下载的字幕文件
            sub_files = list(sub_dir.glob("*.vtt")) + list(sub_dir.glob("*.srt"))
            if not sub_files:
                logger.warning("字幕下载后未找到文件，回退音频模式")
                return None, video_title, None, video_duration

            sub_file = sub_files[0]

            # 从文件名提取语言代码 (e.g. sub.en.vtt → en)
            stem_parts = sub_file.stem.split(".")
            file_lang = stem_parts[-1] if len(stem_parts) > 1 else prefer_lang

            # 4. 解析字幕文件（放到线程里，避免大字幕文件的读取/解析卡住事件循环）
            if sub_file.suffix == ".vtt":
                entries = await asyncio.to_thread(self._parse_vtt, str(sub_file))
            else:
                entries = await asyncio.to_thread(self._parse_srt, str(sub_file))

            if not entries:
                logger.warning("字幕解析结果为空，回退音频模式")
                return None, video_title, None, video_duration

            # 5. 格式化为与 Whisper 输出兼容的 Markdown
            formatted = self._format_subtitle_entries(entries, file_lang)
            logger.info(f"字幕获取成功: lang={file_lang}, {len(entries)} 条目")
            return formatted, video_title, file_lang, video_duration

        except Exception as e:
            logger.warning(f"字幕获取失败（将回退至音频下载）: {e}")
            return None, None, None, 0
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

        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception as e:
            logger.error(f"读取 VTT 文件失败: {e}")
            return []

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

        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception as e:
            logger.error(f"读取 SRT 文件失败: {e}")
            return []

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
    ) -> tuple[str, str]:
        """
        下载媒体并提取音频为m4a格式。

        prefetched_title: 若调用方已通过 fetch_subtitles 探测过媒体信息，
        可直接传入，跳过重复的 extract_info 网络请求。
        """
        try:
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
                # 仅 YouTube 需要 EJS 远程组件；非 YouTube（如 B站）不引入 GitHub 依赖
                **self._youtube_js_opts(url),
            })
            
            logger.info(f"开始下载: {url}")
            
            import asyncio
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                if prefetched_title:
                    # fetch_subtitles 已探测过，直接下载不重复 extract_info
                    video_title = prefetched_title
                    expected_duration = prefetched_duration
                    logger.info(f"复用预取标题: {video_title}, 时长≈{int(expected_duration)}s")
                else:
                    # 获取媒体信息（放到线程池避免阻塞事件循环，超时 60s）
                    info = await asyncio.wait_for(
                        asyncio.to_thread(ydl.extract_info, url, False),
                        timeout=60.0,
                    )
                    video_title = info.get('title', 'unknown')
                    expected_duration = info.get('duration') or 0
                    logger.info(f"标题: {video_title}")
                
                # 播客等大文件（100MB+）在慢速连接下可能远超 5 分钟，
                # 给足兜底时间，避免合法但缓慢的下载被硬超时误杀。
                await self._download_with_timeout(ydl, url, 1800.0, "下载")
            
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
            
            # 校验时长，如果和源文件差异较大，尝试一次ffmpeg规范化重封装
            try:
                import subprocess, shlex

                def _probe_duration(path: str) -> float:
                    probe_cmd = f"ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 {shlex.quote(path)}"
                    out = subprocess.check_output(probe_cmd, shell=True).decode().strip()
                    return float(out) if out else 0.0

                actual_duration = await asyncio.to_thread(_probe_duration, audio_file)
            except Exception as _:
                actual_duration = 0.0

            if expected_duration and actual_duration and abs(actual_duration - expected_duration) / expected_duration > 0.1:
                logger.warning(
                    f"音频时长异常，期望{expected_duration}s，实际{actual_duration}s，尝试重封装修复…"
                )
                try:
                    fixed_path = str(output_dir / f"audio_{unique_id}_fixed.m4a")

                    def _fix_and_probe() -> float:
                        fix_cmd = f"ffmpeg -y -i {shlex.quote(audio_file)} -vn -c:a aac -b:a 160k -movflags +faststart {shlex.quote(fixed_path)}"
                        subprocess.check_call(fix_cmd, shell=True)
                        return _probe_duration(fixed_path)

                    actual_duration2 = await asyncio.to_thread(_fix_and_probe)
                    audio_file = fixed_path
                    logger.info(f"重封装完成，新时长≈{actual_duration2:.2f}s")
                except Exception as e:
                    logger.error(f"重封装失败：{e}")
            
            logger.info(f"音频文件已保存: {audio_file}")
            return audio_file, video_title
            
        except Exception as e:
            logger.error(f"下载失败: {str(e)}", exc_info=True)
            raise Exception(f"下载失败: {str(e)}")

    def get_video_info(self, url: str) -> dict:
        """获取媒体信息"""
        try:
            with yt_dlp.YoutubeDL(self._get_base_opts()) as ydl:
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
            logger.error(f"获取媒体信息失败: {str(e)}")
            raise Exception(f"获取媒体信息失败: {str(e)}")

    async def get_video_title(self, url: str) -> str:
        """快速获取标题（仅探测，不下载）"""
        try:
            import asyncio
            check_opts = self._get_base_opts()
            with yt_dlp.YoutubeDL(check_opts) as ydl:
                info = await asyncio.wait_for(
                    asyncio.to_thread(ydl.extract_info, url, False),
                    timeout=45.0,
                )
                return info.get("title", "unknown")
        except Exception as e:
            logger.error(f"获取标题失败: {e}")
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
            check_opts = self._get_base_opts()
            with yt_dlp.YoutubeDL(check_opts) as ydl:
                info = await asyncio.wait_for(
                    asyncio.to_thread(ydl.extract_info, url, False),
                    timeout=60.0,
                )

            video_formats = []
            audio_formats = []
            # 按用户可见特征去重：(height, vcodec, ext) / (abr, acodec, ext)
            seen_v = {}  # key -> index in video_formats
            seen_a = {}  # key -> index in audio_formats

            # ── 视频格式 ────────────────────────────────────
            video_formats.append({
                "id": "bestvideo+bestaudio/best",
                "ext": "mp4",
                "resolution": "最佳质量",
                "note": "自动选择最佳视频+音频",
                "filesize": info.get("filesize_approx") or 0,
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
                        "id": fid,
                        "ext": ext,
                        "resolution": resolution,
                        "height": height,
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
                    "note": "最佳音质（自动选择）",
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
            logger.error(f"获取媒体格式失败: {e}")
            raise Exception(f"获取媒体格式失败: {str(e)}")

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

            dl_opts = self._get_download_opts(url, {
                "format": format_id,
                "outtmpl": output_template,
                "merge_output_format": "mp4",
            })

            logger.info(f"开始下载: {url} (format={format_id})")

            with yt_dlp.YoutubeDL(dl_opts) as ydl:
                await self._download_with_timeout(ydl, url, 1800.0, "下载")

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
            logger.error(f"下载失败: {e}", exc_info=True)
            raise Exception(f"下载失败: {str(e)}")

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

            logger.info(f"开始下载音频: {url} (format={format_id})")

            with yt_dlp.YoutubeDL(dl_opts) as ydl:
                await self._download_with_timeout(ydl, url, 1800.0, "下载音频")

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
            logger.error(f"下载音频失败: {e}", exc_info=True)
            raise Exception(f"下载音频失败: {str(e)}")

    async def download_subtitles_file(
        self, url: str, output_dir: Path, lang: str = "en",
        filename_base: str = ""
    ) -> tuple[str, str]:
        """仅下载字幕文件，返回 (文件路径, 语言代码)。"""
        try:
            import asyncio
            output_dir.mkdir(exist_ok=True)

            # 先探测字幕可用性
            check_opts = self._get_base_opts()
            with yt_dlp.YoutubeDL(check_opts) as ydl:
                info = await asyncio.wait_for(
                    asyncio.to_thread(ydl.extract_info, url, False),
                    timeout=60.0,
                )

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

            dl_opts = self._get_base_opts({
                "writesubtitles": prefer_manual,
                "writeautomaticsub": not prefer_manual,
                "subtitlesformat": "vtt/srt/best",
                "subtitleslangs": [chosen_lang],
                "skip_download": True,
                "outtmpl": output_template,
            })

            with yt_dlp.YoutubeDL(dl_opts) as ydl:
                # 下载字幕文件，体积小，给较短兜底超时
                await self._download_with_timeout(ydl, url, 120.0, "下载字幕")

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
            logger.error(f"下载字幕失败: {e}")
            raise Exception(f"下载字幕失败: {str(e)}")

    @staticmethod
    def _sanitize_filename(name: str) -> str:
        """安全化文件名"""
        name = re.sub(r'[<>:"/\\|?*]', "_", name)
        name = re.sub(r"\s+", "_", name).strip("._ ")
        return name[:100] or "video"
