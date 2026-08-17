"""媒体恢复的宿主动作：闭集参数、受限网络与宿主产物验证。"""
from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import mimetypes
import re
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Callable, Optional, Sequence

import cancellation
from cancellation import CancelledByUser
from candidate_parser import CandidateParserRuntime, CandidateResultKind
from media_contracts import (
    ExtractionFailure,
    ExtractionFailureKind,
    ObservationStatus,
    RecoveryAction,
    RecoveryObservation,
    SubtitleFetchStatus,
    sanitize_diagnostic,
    sanitize_plain_text,
)
from llm_tools import host_function_tool, string_prop
from media_recovery import (
    REQUESTABLE_USER_ACTION_CODES,
    RecoveryResult,
    RecoveryRunStatus,
    UserActionCode,
)
from runtime_environment import runtime_observation_summary
from video_processor import probe_duration
from yt_dlp_updater import retry_update_async, update_status

logger = logging.getLogger(__name__)

_MAX_HTTP_BODY = 256 * 1024
_MAX_DOWNLOAD_BYTES = 512 * 1024 * 1024
_URL_IN_BODY_RE = re.compile(r"https?://[^\s\"'<>\\]+", re.IGNORECASE)
_ALLOWED_USER_ACTIONS = {item.value: item for item in UserActionCode}
_BASE_YTDLP_PROFILES = {"metadata", "subtitles", "audio"}
_PLATFORM_MEDIA_DOMAINS = {
    "youtube": ("youtube.com", "youtu.be", "googlevideo.com", "ytimg.com"),
    "bilibili": ("bilibili.com", "b23.tv", "bilivideo.com", "hdslb.com"),
}


class _RestrictedRedirectHandler(urllib.request.HTTPRedirectHandler):
    def __init__(self, validator):
        super().__init__()
        self._validator = validator

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        self._validator(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class MediaRecoveryActions:
    """单次恢复运行的有状态动作集合；实例不跨任务共享。"""

    def __init__(
        self,
        *,
        source_url: str,
        failure: ExtractionFailure,
        video_processor,
        temp_dir: Path,
        set_user_message: Optional[Callable[[str], Any]] = None,
        allowed_user_actions: Optional[set[UserActionCode]] = None,
    ):
        self._source_url = source_url
        self._failure = failure
        self._video_processor = video_processor
        self._temp_dir = Path(temp_dir)
        self._set_user_message = set_user_message
        requested = REQUESTABLE_USER_ACTION_CODES if allowed_user_actions is None else allowed_user_actions
        self._allowed_user_actions = {
            item if isinstance(item, UserActionCode) else UserActionCode(item)
            for item in requested
            if (item if isinstance(item, UserActionCode) else UserActionCode(item)) in REQUESTABLE_USER_ACTION_CODES
        }
        self._pending_user: Optional[tuple[UserActionCode, str]] = None
        self._media_path: Optional[str] = None
        self._subtitle_text: Optional[str] = None
        self._title: Optional[str] = None
        self._language: Optional[str] = None
        self._artifact_verified = False
        self._http_bodies: dict[str, bytes] = {}
        self._candidates: dict[str, str] = {}
        self._candidate_types: dict[str, str] = {}
        self._request_proposals: dict[str, tuple[str, str]] = {}
        self._downloaded_candidate: Optional[str] = None
        self._downloaded_candidate_type: Optional[str] = None
        self._candidate_runs = 0
        self._candidate_runtime = CandidateParserRuntime(temp_dir=self._temp_dir)

    def action_specs(self) -> Sequence[dict[str, Any]]:
        profiles = sorted(self._allowed_ytdlp_profiles())
        user_actions = sorted(item.value for item in self._allowed_user_actions)
        return (
            host_function_tool(
                "inspect_failure",
                "Read the sanitized extraction failure for this run. Use before choosing a recovery path. Does not change anything or reveal the source URL.",
                capability="read",
                timeout_sec=5,
            ),
            host_function_tool(
                "inspect_runtime",
                "Read whether FFmpeg, FFprobe, Deno, MLX, yt-dlp, the default Whisper model, and a browser session are ready. Use when the failure may be environmental. Does not change anything.",
                capability="read",
                timeout_sec=5,
            ),
            host_function_tool(
                "run_ytdlp",
                "Run one host-approved media extraction profile. Use to retry metadata, subtitles, or audio. Accepts only a listed profile, never raw yt-dlp options or commands.",
                capability="mutate",
                timeout_sec=60,
                properties={"profile": string_prop("Host-approved extraction profile", enum=profiles)},
                required=["profile"],
            ),
            host_function_tool(
                "prepare_ytdlp_update",
                "Start the host-managed stable yt-dlp update check in the background. Use when the extractor may be outdated. Does not wait for or activate the update in this run.",
                capability="mutate",
                timeout_sec=5,
            ),
            host_function_tool(
                "http_request",
                "Fetch one host-approved platform URL or parser proposal with GET or HEAD. Use path or proposal_id, not both. Cannot access arbitrary domains, local addresses, or add headers.",
                capability="mutate",
                timeout_sec=30,
                properties={
                    "method": string_prop("HTTP method when using path", enum=["GET", "HEAD"]),
                    "path": string_prop("Host-approved URL or path. Do not send with proposal_id."),
                    "proposal_id": string_prop("Previously listed proposal_N. Do not send with path."),
                },
            ),
            host_function_tool(
                "run_candidate_parser",
                "Run one single-use JavaScript candidate parser against a saved response. Use only for changed public response structures. It has no file, network, environment, or subprocess access.",
                capability="mutate",
                timeout_sec=20,
                properties={
                    "response_id": string_prop("Saved response_N from http_request"),
                    "source": string_prop("Single-use JavaScript, at most 20KB"),
                },
                required=["response_id", "source"],
            ),
            host_function_tool(
                "use_browser_session",
                "Check and use the host-approved opaque browser session for this task. Use when login may be required. Never exposes cookies or tokens to the model.",
                capability="mutate",
                timeout_sec=5,
            ),
            host_function_tool(
                "request_youtube_challenge_capability",
                "Check whether the host already has approved YouTube challenge support. Use for challenge failures. Does not create tokens, bypass access controls, or install software.",
                capability="mutate",
                timeout_sec=5,
            ),
            host_function_tool(
                "download_candidate",
                "Download one candidate previously accepted by the host. Use only with a listed candidate ID. Cannot download an arbitrary URL and does not validate the artifact.",
                capability="mutate",
                timeout_sec=60,
                properties={"candidate_id": string_prop("Previously listed candidate_N")},
                required=["candidate_id"],
            ),
            host_function_tool(
                "validate_media",
                "Validate the current media candidate with host file and duration checks. Use before declaring media recovery complete. Does not download or modify media.",
                capability="mutate",
                timeout_sec=10,
            ),
            host_function_tool(
                "validate_subtitle",
                "Validate that the current subtitle candidate is non-empty and within host limits. Use before declaring subtitle recovery complete. Does not fetch subtitles.",
                capability="mutate",
                timeout_sec=5,
            ),
            host_function_tool(
                "set_user_message",
                "Replace the task's short user-visible recovery status with sanitized plain text. Use for useful progress only. Cannot include HTML, secrets, or more than 300 characters.",
                capability="mutate",
                timeout_sec=5,
                properties={"message": string_prop("Plain text, at most 300 characters")},
                required=["message"],
            ),
            host_function_tool(
                "ask_user",
                "Stop this run and request one fixed host-approved user action. Use only when recovery cannot continue automatically. The action_code must be listed and no extra payload is allowed.",
                capability="mutate",
                timeout_sec=5,
                properties={
                    "action_code": string_prop("Host-approved user action", enum=user_actions),
                    "message": string_prop("Plain text shown to the user"),
                },
                required=["action_code", "message"],
            ),
        )

    async def execute(self, action: RecoveryAction, arguments: dict[str, Any]) -> RecoveryObservation:
        if not isinstance(arguments, dict):
            return self._failure_observation(action, "invalid_arguments", "动作参数必须是对象。")
        handler = {
            RecoveryAction.INSPECT_FAILURE: self._inspect_failure,
            RecoveryAction.INSPECT_RUNTIME: self._inspect_runtime,
            RecoveryAction.RUN_YTDLP: self._run_ytdlp,
            RecoveryAction.PREPARE_YTDLP_UPDATE: self._prepare_ytdlp_update,
            RecoveryAction.HTTP_REQUEST: self._http_request,
            RecoveryAction.RUN_CANDIDATE_PARSER: self._run_candidate_parser,
            RecoveryAction.USE_BROWSER_SESSION: self._use_browser_session,
            RecoveryAction.REQUEST_YOUTUBE_CHALLENGE_CAPABILITY: self._request_challenge,
            RecoveryAction.DOWNLOAD_CANDIDATE: self._download_candidate,
            RecoveryAction.VALIDATE_MEDIA: self._validate_media,
            RecoveryAction.VALIDATE_SUBTITLE: self._validate_subtitle,
            RecoveryAction.SET_USER_MESSAGE: self._message,
            RecoveryAction.ASK_USER: self._ask_user,
        }[action]
        try:
            return await handler(arguments)
        except (ValueError, TypeError) as exc:
            return self._failure_observation(action, "invalid_arguments", str(exc))

    def verified_result(self, observations: tuple[RecoveryObservation, ...]) -> Optional[RecoveryResult]:
        if not self._artifact_verified:
            return None
        return RecoveryResult(
            status=RecoveryRunStatus.RECOVERED,
            code="artifact_verified",
            message="宿主已验证恢复产物。",
            media_path=self._media_path,
            subtitle_text=self._subtitle_text,
            title=self._title,
            language=self._language,
            observations=observations,
        )

    def pending_user_action(self) -> Optional[tuple[UserActionCode, str]]:
        return self._pending_user

    async def _inspect_failure(self, arguments: dict[str, Any]) -> RecoveryObservation:
        self._expect_keys(arguments)
        f = self._failure
        summary = (
            f"platform={f.platform}; stage={f.stage.value}; kind={f.kind.value}; "
            f"yt_dlp={f.yt_dlp_version or 'unknown'}; cookie={f.cookie_available}; "
            f"deno={f.deno_available}; ejs={f.ejs_available}; detail={f.sanitized_summary}"
        )
        return self._success(RecoveryAction.INSPECT_FAILURE, "failure_inspected", summary)

    async def _inspect_runtime(self, arguments: dict[str, Any]) -> RecoveryObservation:
        self._expect_keys(arguments)
        summary = (
            f"{runtime_observation_summary()}; "
            f"browser_session_available={self._browser_session_available()}; "
            f"failure_deno={self._failure.deno_available}; "
            f"failure_ejs={self._failure.ejs_available}"
        )
        return self._success(RecoveryAction.INSPECT_RUNTIME, "runtime_inspected", summary)

    async def _run_ytdlp(self, arguments: dict[str, Any]) -> RecoveryObservation:
        self._expect_keys(arguments, "profile")
        profile = arguments.get("profile")
        allowed_profiles = self._allowed_ytdlp_profiles()
        if profile not in allowed_profiles:
            raise ValueError("未允许的 yt-dlp profile")
        if profile == "metadata":
            opts = self._video_processor._get_extract_opts(self._source_url)
            info, _ = await self._video_processor._extract_info_with_cookie_fallback(
                self._source_url, opts, 45.0
            )
            self._title = sanitize_diagnostic(info.get("title") or "", max_length=160) or None
            has_audio = any(
                (item.get("acodec") or "none") != "none"
                for item in (info.get("formats") or [])
                if isinstance(item, dict)
            )
            return self._success(
                RecoveryAction.RUN_YTDLP,
                "metadata_available",
                f"profile=metadata; has_audio={has_audio}; title_available={bool(self._title)}",
            )
        if profile == "subtitles":
            result = await self._video_processor.fetch_subtitles(self._source_url, self._temp_dir)
            if result.status is SubtitleFetchStatus.FOUND:
                self._subtitle_text = result.text
                self._title = result.title
                self._language = result.language
                self._artifact_verified = bool((result.text or "").strip())
                return self._success(RecoveryAction.RUN_YTDLP, "subtitle_found", "yt-dlp 返回了可验证字幕。")
            if result.status is SubtitleFetchStatus.NO_SUBTITLES:
                return self._failure_observation(RecoveryAction.RUN_YTDLP, "no_subtitles", "来源确认没有可用字幕。")
            return RecoveryObservation(
                action=RecoveryAction.RUN_YTDLP,
                status=ObservationStatus.FAILURE,
                code="ytdlp_failed",
                sanitized_summary=(result.failure.sanitized_summary if result.failure else "字幕恢复失败。"),
                failure=result.failure,
            )

        recovery_profile = None if profile == "audio" else profile
        path, title = await self._video_processor.download_and_convert(
            self._source_url,
            self._temp_dir,
            recovery_profile=recovery_profile,
        )
        self._media_path = path
        self._title = title
        duration = await asyncio.to_thread(probe_duration, path)
        self._artifact_verified = Path(path).is_file() and Path(path).stat().st_size > 0 and duration > 0
        if not self._artifact_verified:
            return self._failure_observation(RecoveryAction.RUN_YTDLP, "media_invalid", "yt-dlp 产物未通过宿主验证。")
        return self._success(RecoveryAction.RUN_YTDLP, "media_downloaded", f"宿主已验证音频，duration={duration:.1f}s")

    async def _prepare_ytdlp_update(self, arguments: dict[str, Any]) -> RecoveryObservation:
        self._expect_keys(arguments)
        retry_update_async()
        state = update_status()
        return self._success(
            RecoveryAction.PREPARE_YTDLP_UPDATE,
            "update_scheduled",
            f"yt-dlp stable 更新检查已启动；当前版本={state.get('current_version') or 'unknown'}；新版本通常下次启动生效。",
        )

    async def _http_request(self, arguments: dict[str, Any]) -> RecoveryObservation:
        self._expect_keys(arguments, "method", "path", "proposal_id")
        proposal_id = str(arguments.get("proposal_id") or "")
        if proposal_id:
            proposal = self._request_proposals.get(proposal_id)
            if proposal is None:
                raise ValueError("未知 proposal_id")
            method, target = proposal
            if arguments.get("path"):
                raise ValueError("proposal_id 与 path 不能同时使用")
        else:
            method = str(arguments.get("method") or "GET").upper()
            target = urllib.parse.urljoin(self._source_url, str(arguments.get("path") or self._source_url))
        if method not in {"GET", "HEAD"}:
            raise ValueError("HTTP 方法只允许 GET/HEAD")
        self._validate_url(target)

        def _request():
            opener = urllib.request.build_opener(_RestrictedRedirectHandler(self._validate_url))
            req = urllib.request.Request(
                target,
                method=method,
                headers={"User-Agent": "MediaBrief-Recovery/1.0", "Accept": "application/json,text/html,*/*;q=0.5"},
            )
            with opener.open(req, timeout=20) as response:
                body = b"" if method == "HEAD" else response.read(_MAX_HTTP_BODY + 1)
                if len(body) > _MAX_HTTP_BODY:
                    raise ValueError("HTTP 响应超过大小限制")
                return response.status, response.headers.get_content_type(), body

        status, content_type, body = await asyncio.to_thread(_request)
        response_id = f"response_{len(self._http_bodies) + 1}"
        self._http_bodies[response_id] = body
        candidate_count = self._collect_candidates(body)
        preview = self._safe_structure_preview(body, content_type)
        summary = (
            f"response_id={response_id}; status={status}; content_type={content_type}; "
            f"bytes={len(body)}; candidates_added={candidate_count}; structure={preview}"
        )
        return self._success(RecoveryAction.HTTP_REQUEST, "http_response", summary)

    async def _run_candidate_parser(self, arguments: dict[str, Any]) -> RecoveryObservation:
        self._expect_keys(arguments, "response_id", "source")
        if self._failure.kind in {
            ExtractionFailureKind.AUTH_REQUIRED,
            ExtractionFailureKind.PERMISSION_DENIED,
            ExtractionFailureKind.CHALLENGE_REQUIRED,
            ExtractionFailureKind.DRM_PROTECTED,
        }:
            return self._failure_observation(
                RecoveryAction.RUN_CANDIDATE_PARSER,
                "access_control_not_parseable",
                "登录、权限、challenge、会员或地区限制不能通过候选解析器恢复。",
            )
        if self._candidate_runs >= 1:
            return self._failure_observation(
                RecoveryAction.RUN_CANDIDATE_PARSER,
                "candidate_budget_exhausted",
                "当前任务的一次性候选解析器运行次数已用尽。",
            )
        response_id = str(arguments.get("response_id") or "")
        body = self._http_bodies.get(response_id)
        if body is None:
            raise ValueError("未知 response_id")
        source = arguments.get("source")
        if not isinstance(source, str):
            raise ValueError("候选源码必须是字符串")
        self._candidate_runs += 1
        if not await self._candidate_runtime.verify_boundary():
            return self._failure_observation(
                RecoveryAction.RUN_CANDIDATE_PARSER,
                "candidate_runtime_unavailable",
                "Deno 运行时未通过无网络/文件/环境/子进程边界验证，候选代码已禁用。",
            )
        parsed = await self._candidate_runtime.run(source, {
            "platform": self._failure.platform,
            "source_url": self._source_url,
            "response_id": response_id,
            "body": body.decode("utf-8", "replace"),
        })
        if parsed.kind is CandidateResultKind.CANDIDATES:
            added = 0
            for item in parsed.candidates:
                try:
                    self._validate_url(item.url)
                except ValueError:
                    continue
                candidate_id = f"candidate_{len(self._candidates) + 1}"
                self._candidates[candidate_id] = item.url
                self._candidate_types[candidate_id] = item.resource_type
                added += 1
            if not added:
                return self._failure_observation(
                    RecoveryAction.RUN_CANDIDATE_PARSER,
                    "candidate_urls_rejected",
                    "候选解析器输出的资源均未通过宿主域名校验。",
                )
            return self._success(
                RecoveryAction.RUN_CANDIDATE_PARSER,
                "candidate_resources",
                f"宿主接受 {added} 个候选资源；可用 ID=candidate_1..candidate_{len(self._candidates)}",
            )
        if parsed.kind is CandidateResultKind.REQUEST_PROPOSAL:
            self._validate_url(parsed.request_url or "")
            proposal_id = f"proposal_{len(self._request_proposals) + 1}"
            self._request_proposals[proposal_id] = (parsed.request_method or "GET", parsed.request_url or "")
            return self._success(
                RecoveryAction.RUN_CANDIDATE_PARSER,
                "request_proposal",
                f"候选解析器提出下一请求；proposal_id={proposal_id}，须由宿主执行。",
            )
        return self._failure_observation(
            RecoveryAction.RUN_CANDIDATE_PARSER,
            "candidate_no_result",
            parsed.diagnostic or "候选解析器未找到资源。",
        )

    async def _use_browser_session(self, arguments: dict[str, Any]) -> RecoveryObservation:
        self._expect_keys(arguments)
        if self._browser_session_available():
            return self._success(
                RecoveryAction.USE_BROWSER_SESSION,
                "browser_session_available",
                "宿主已获准使用不透明浏览器会话；模型不可见 Cookie 或 Token。",
            )
        return self._failure_observation(
            RecoveryAction.USE_BROWSER_SESSION,
            "browser_session_unavailable",
            "当前任务未获准使用浏览器会话，需要通过 ask_user 请求固定用户动作。",
        )

    async def _request_challenge(self, arguments: dict[str, Any]) -> RecoveryObservation:
        self._expect_keys(arguments)
        if self._failure.ejs_available:
            return self._success(
                RecoveryAction.REQUEST_YOUTUBE_CHALLENGE_CAPABILITY,
                "challenge_capability_available",
                "宿主已配置 YouTube EJS/JS capability；内部令牌不会暴露给模型。",
            )
        return self._failure_observation(
            RecoveryAction.REQUEST_YOUTUBE_CHALLENGE_CAPABILITY,
            "challenge_capability_unavailable",
            "宿主没有可用的 YouTube challenge capability。",
        )

    async def _download_candidate(self, arguments: dict[str, Any]) -> RecoveryObservation:
        self._expect_keys(arguments, "candidate_id")
        candidate_id = str(arguments.get("candidate_id") or "")
        target = self._candidates.get(candidate_id)
        if not target:
            raise ValueError("未知 candidate_id")
        self._validate_url(target)
        suffix = Path(urllib.parse.urlsplit(target).path).suffix[:10] or ".bin"
        self._temp_dir.mkdir(parents=True, exist_ok=True)
        output = self._temp_dir / f"recovery_{uuid.uuid4().hex[:10]}{suffix}"

        def _download():
            opener = urllib.request.build_opener(_RestrictedRedirectHandler(self._validate_url))
            req = urllib.request.Request(target, headers={"User-Agent": "MediaBrief-Recovery/1.0"})
            total = 0
            with opener.open(req, timeout=30) as response, output.open("wb") as handle:
                while True:
                    token = cancellation.current()
                    if token is not None and token.is_cancelled():
                        raise CancelledByUser()
                    chunk = response.read(64 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > _MAX_DOWNLOAD_BYTES:
                        raise ValueError("候选下载超过大小限制")
                    handle.write(chunk)
            return total

        try:
            total = await asyncio.to_thread(_download)
        except Exception:
            output.unlink(missing_ok=True)
            raise
        self._downloaded_candidate = str(output)
        self._downloaded_candidate_type = self._candidate_types.get(candidate_id, "media")
        if self._downloaded_candidate_type == "subtitle":
            raw = output.read_bytes()
            if len(raw) > 20_000_000:
                raise ValueError("字幕候选超过大小限制")
            self._subtitle_text = raw.decode("utf-8", "replace")
        else:
            self._media_path = str(output)
        return self._success(RecoveryAction.DOWNLOAD_CANDIDATE, "candidate_downloaded", f"候选已下载；bytes={total}")

    async def _validate_media(self, arguments: dict[str, Any]) -> RecoveryObservation:
        self._expect_keys(arguments)
        path = self._media_path or self._downloaded_candidate
        if not path or not Path(path).is_file() or Path(path).stat().st_size <= 0:
            return self._failure_observation(RecoveryAction.VALIDATE_MEDIA, "media_missing", "没有可供验证的媒体候选。")
        try:
            duration = await asyncio.to_thread(probe_duration, path)
        except Exception as exc:
            return self._failure_observation(RecoveryAction.VALIDATE_MEDIA, "media_probe_failed", str(exc))
        self._artifact_verified = duration > 0
        if not self._artifact_verified:
            return self._failure_observation(RecoveryAction.VALIDATE_MEDIA, "media_invalid", "媒体没有有效时长或音轨。")
        return self._success(RecoveryAction.VALIDATE_MEDIA, "media_valid", f"媒体通过宿主验证；duration={duration:.1f}s")

    async def _validate_subtitle(self, arguments: dict[str, Any]) -> RecoveryObservation:
        self._expect_keys(arguments)
        text = (self._subtitle_text or "").strip()
        self._artifact_verified = bool(text and len(text) <= 20_000_000)
        if not self._artifact_verified:
            return self._failure_observation(RecoveryAction.VALIDATE_SUBTITLE, "subtitle_invalid", "没有非空字幕可供验证。")
        return self._success(RecoveryAction.VALIDATE_SUBTITLE, "subtitle_valid", "字幕通过宿主非空与大小验证。")

    async def _message(self, arguments: dict[str, Any]) -> RecoveryObservation:
        self._expect_keys(arguments, "message")
        message = sanitize_plain_text(arguments.get("message"), max_length=300)
        if not message:
            raise ValueError("message 不能为空")
        if self._set_user_message is not None:
            result = self._set_user_message(message)
            if hasattr(result, "__await__"):
                await result
        return self._success(RecoveryAction.SET_USER_MESSAGE, "message_updated", message)

    async def _ask_user(self, arguments: dict[str, Any]) -> RecoveryObservation:
        self._expect_keys(arguments, "action_code", "message")
        action_code = str(arguments.get("action_code") or "")
        action = _ALLOWED_USER_ACTIONS.get(action_code)
        if action is None or action not in self._allowed_user_actions:
            raise ValueError("未允许的用户动作")
        message = sanitize_plain_text(arguments.get("message"), max_length=500) or "需要用户操作后重试。"
        self._pending_user = (action, message)
        return self._success(RecoveryAction.ASK_USER, "user_action_requested", message)

    def _browser_session_available(self) -> bool:
        checker = getattr(self._video_processor, "browser_session_available", None)
        if callable(checker):
            return bool(checker())
        return bool(getattr(self._video_processor, "_cookies_opts", {}))

    def _validate_url(self, target: str) -> None:
        source = urllib.parse.urlsplit(self._source_url)
        parsed = urllib.parse.urlsplit(target)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("HTTP 目标无效")
        low_host = parsed.hostname.lower().rstrip(".")
        source_host = (source.hostname or "").lower().rstrip(".")
        allowed_domains = _PLATFORM_MEDIA_DOMAINS.get(self._failure.platform, ())
        domain_allowed = low_host == source_host or any(
            low_host == domain or low_host.endswith("." + domain)
            for domain in allowed_domains
        )
        if not domain_allowed:
            raise ValueError("HTTP 目标不在来源或平台媒体域名白名单")
        if low_host == "localhost" or low_host.endswith(".localhost"):
            raise ValueError("不允许访问本机地址")
        try:
            ip = ipaddress.ip_address(low_host)
        except ValueError:
            return
        if not ip.is_global:
            raise ValueError("不允许访问非公网地址")

    def _collect_candidates(self, body: bytes) -> int:
        text = body.decode("utf-8", "replace")
        added = 0
        for raw in _URL_IN_BODY_RE.findall(text):
            candidate = raw.replace("\\u0026", "&").replace("\\/", "/")
            try:
                self._validate_url(candidate)
            except ValueError:
                continue
            candidate_id = f"candidate_{len(self._candidates) + 1}"
            self._candidates[candidate_id] = candidate
            self._candidate_types[candidate_id] = "media"
            added += 1
            if added >= 20:
                break
        return added

    @staticmethod
    def _safe_structure_preview(body: bytes, content_type: str) -> str:
        """只给模型结构和脱敏短样本，不把网页原文或认证值放进上下文。"""
        text = body[:32_000].decode("utf-8", "replace")
        if "json" in (content_type or ""):
            try:
                value = json.loads(text)
            except json.JSONDecodeError:
                pass
            else:
                sensitive = re.compile(r"(?i)token|cookie|auth|password|secret|signature|key")

                def _shape(item, depth=0):
                    if depth >= 3:
                        return type(item).__name__
                    if isinstance(item, dict):
                        return {
                            str(key)[:60]: "[redacted]" if sensitive.search(str(key)) else _shape(val, depth + 1)
                            for key, val in list(item.items())[:30]
                        }
                    if isinstance(item, list):
                        return [_shape(val, depth + 1) for val in item[:2]]
                    if isinstance(item, str):
                        return sanitize_diagnostic(item, max_length=80)
                    return item

                return sanitize_diagnostic(
                    json.dumps(_shape(value), ensure_ascii=False),
                    max_length=700,
                )
        return sanitize_diagnostic(text, max_length=700)

    def _allowed_ytdlp_profiles(self) -> set[str]:
        names = set(_BASE_YTDLP_PROFILES)
        getter = getattr(self._video_processor, "recovery_profile_names", None)
        if callable(getter):
            names.update(getter(self._source_url))
        return names

    @staticmethod
    def _expect_keys(arguments: dict[str, Any], *allowed: str) -> None:
        extras = set(arguments) - set(allowed)
        if extras:
            raise ValueError(f"动作包含未允许参数：{','.join(sorted(extras))}")

    @staticmethod
    def _success(action: RecoveryAction, code: str, summary: str) -> RecoveryObservation:
        return RecoveryObservation(
            action=action,
            status=ObservationStatus.SUCCESS,
            code=code,
            sanitized_summary=summary,
        )

    @staticmethod
    def _failure_observation(action: RecoveryAction, code: str, summary: str) -> RecoveryObservation:
        return RecoveryObservation(
            action=action,
            status=ObservationStatus.FAILURE,
            code=code,
            sanitized_summary=summary,
        )
