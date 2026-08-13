"""一次性 Deno 媒体解析器运行时；默认无任何 Deno 权限。"""
from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import uuid
from dataclasses import dataclass
from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

import cancellation
from cancellation import CancelledByUser
from media_contracts import sanitize_diagnostic


MAX_SOURCE_BYTES = 20_000
MAX_INPUT_BYTES = 256 * 1024
MAX_OUTPUT_BYTES = 64 * 1024
MAX_CANDIDATES = 20
_FORBIDDEN_SOURCE_RE = re.compile(
    r"\b(?:import|require|fetch|WebSocket|EventSource|Worker)\b|"
    r"\bDeno\s*\.\s*(?:Command|run|open|read[A-Za-z]*|write[A-Za-z]*|env|cwd|chdir|"
    r"dlopen|permissions|createHttpClient|listen|connect|serve|upgradeWebSocket)\b",
    re.IGNORECASE,
)


class CandidateResultKind(str, Enum):
    CANDIDATES = "candidates"
    REQUEST_PROPOSAL = "request_proposal"
    FAILED = "failed"


@dataclass(frozen=True)
class CandidateResource:
    url: str
    resource_type: str


@dataclass(frozen=True)
class CandidateParserResult:
    kind: CandidateResultKind
    candidates: tuple[CandidateResource, ...] = ()
    request_method: Optional[str] = None
    request_url: Optional[str] = None
    diagnostic: str = ""


class CandidateParserRuntime:
    def __init__(self, *, temp_dir: Path, deno_path: Optional[str] = None, timeout_sec: float = 3.0):
        self._temp_dir = Path(temp_dir)
        self._deno = deno_path or _find_deno()
        self._timeout_sec = timeout_sec

    @property
    def available(self) -> bool:
        return bool(self._deno and Path(self._deno).is_file() and os.access(self._deno, os.X_OK))

    async def run(self, source: str, payload: dict[str, Any]) -> CandidateParserResult:
        self._validate_source(source)
        raw_input = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        if len(raw_input) > MAX_INPUT_BYTES:
            raise ValueError("候选解析器输入超过大小限制")
        output = await asyncio.to_thread(self._run_raw, source, raw_input)
        return self._parse_output(output)

    async def verify_boundary(self) -> bool:
        """真实启动 Deno，确认四类敏感能力在无权限模式下均被拒绝。"""
        if not self.available:
            return False
        source = r'''
const denied = {};
for (const [name, fn] of [
  ["env", () => Deno.env.get("HOME")],
  ["file", () => Deno.readTextFileSync("/etc/passwd")],
  ["network", () => fetch("https://example.com")],
  ["process", () => new Deno.Command("echo", {args:["unsafe"]}).outputSync()],
]) {
  try { const value = fn(); if (value instanceof Promise) await value; denied[name] = false; }
  catch (_) { denied[name] = true; }
}
console.log(JSON.stringify(denied));
'''
        try:
            raw = await asyncio.to_thread(self._run_raw, source, b"{}")
            result = json.loads(raw.decode("utf-8"))
        except Exception:
            return False
        return result == {"env": True, "file": True, "network": True, "process": True}

    def _validate_source(self, source: str) -> None:
        if not isinstance(source, str) or not source.strip():
            raise ValueError("候选解析器源码不能为空")
        if len(source.encode("utf-8")) > MAX_SOURCE_BYTES:
            raise ValueError("候选解析器源码超过大小限制")
        if _FORBIDDEN_SOURCE_RE.search(source):
            raise ValueError("候选解析器源码请求了未允许能力")

    def _run_raw(self, source: str, raw_input: bytes) -> bytes:
        if not self.available:
            raise RuntimeError("Deno 候选解析器运行时不可用")
        self._temp_dir.mkdir(parents=True, exist_ok=True)
        source_path = self._temp_dir / f"candidate_{uuid.uuid4().hex}.js"
        source_path.write_text(source, encoding="utf-8")
        cmd = [
            str(self._deno), "run", "--quiet", "--no-prompt", "--no-config", "--no-lock",
            "--cached-only", "--v8-flags=--max-old-space-size=128", str(source_path),
        ]
        env = {"PATH": str(Path(self._deno).parent)}
        with tempfile.TemporaryFile() as stdout_file, tempfile.TemporaryFile() as stderr_file:
            kwargs = {
                "stdin": subprocess.PIPE,
                # 不把不可信 stdout/stderr 收进内存；临时文件在关闭时自动删除。
                "stdout": stdout_file,
                "stderr": stderr_file,
                "env": env,
            }
            if os.name == "posix":
                kwargs["start_new_session"] = True
            proc = subprocess.Popen(cmd, **kwargs)
            token = cancellation.current()
            if token is not None:
                token.register_process(proc)
            try:
                try:
                    proc.communicate(raw_input, timeout=self._timeout_sec)
                except subprocess.TimeoutExpired:
                    if os.name == "posix":
                        try:
                            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                    else:
                        proc.kill()
                    proc.communicate()
                    raise TimeoutError("候选解析器运行超时")
            finally:
                if token is not None:
                    token.unregister_process(proc)
                source_path.unlink(missing_ok=True)
            stdout_file.seek(0)
            stdout = stdout_file.read(MAX_OUTPUT_BYTES + 1)
            stderr_file.seek(0)
            stderr = stderr_file.read(8_001)
        if token is not None and token.is_cancelled():
            raise CancelledByUser()
        if len(stdout) > MAX_OUTPUT_BYTES:
            raise ValueError("候选解析器输出超过大小限制")
        if proc.returncode != 0:
            safe = sanitize_diagnostic(stderr[:8_000].decode("utf-8", "replace"))
            raise RuntimeError(f"候选解析器失败: {safe}")
        return stdout

    @staticmethod
    def _parse_output(raw: bytes) -> CandidateParserResult:
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("候选解析器必须只输出一个 JSON 对象") from exc
        if not isinstance(data, dict):
            raise ValueError("候选解析器输出必须是对象")
        try:
            kind = CandidateResultKind(data.get("kind"))
        except (TypeError, ValueError) as exc:
            raise ValueError("候选解析器输出 kind 无效") from exc
        allowed_top = {"kind", "candidates", "request", "diagnostic"}
        if set(data) - allowed_top:
            raise ValueError("候选解析器输出包含未知字段")
        diagnostic = sanitize_diagnostic(data.get("diagnostic"), max_length=500)
        if kind is CandidateResultKind.CANDIDATES:
            items = data.get("candidates")
            if not isinstance(items, list) or not items or len(items) > MAX_CANDIDATES:
                raise ValueError("候选列表为空或超过上限")
            candidates = []
            for item in items:
                if not isinstance(item, dict) or set(item) != {"url", "type"}:
                    raise ValueError("候选资源字段无效")
                resource_type = str(item.get("type") or "")
                if resource_type not in {"media", "subtitle"}:
                    raise ValueError("候选资源类型无效")
                url = str(item.get("url") or "")
                if not url:
                    raise ValueError("候选资源 URL 不能为空")
                candidates.append(CandidateResource(url=url, resource_type=resource_type))
            return CandidateParserResult(kind=kind, candidates=tuple(candidates), diagnostic=diagnostic)
        if kind is CandidateResultKind.REQUEST_PROPOSAL:
            request = data.get("request")
            if not isinstance(request, dict) or set(request) != {"method", "url"}:
                raise ValueError("request proposal 字段无效")
            method = str(request.get("method") or "").upper()
            if method not in {"GET", "HEAD"}:
                raise ValueError("request proposal 方法无效")
            url = str(request.get("url") or "")
            if not url:
                raise ValueError("request proposal URL 不能为空")
            return CandidateParserResult(
                kind=kind,
                request_method=method,
                request_url=url,
                diagnostic=diagnostic,
            )
        return CandidateParserResult(kind=kind, diagnostic=diagnostic or "候选解析器未找到资源")


def _find_deno() -> Optional[str]:
    exe = "deno.exe" if sys.platform == "win32" else "deno"
    candidates = [
        Path(sys.executable).resolve().parent / exe,
        Path(getattr(sys, "_MEIPASS", "")) / "deno_bin" / exe if getattr(sys, "frozen", False) else None,
    ]
    for item in candidates:
        if item and item.is_file() and os.access(item, os.X_OK):
            return str(item)
    return shutil.which("deno")
