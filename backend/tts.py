"""豆包语音合成：HTTP 单向流式接口（seed-tts-2.0）。

对标 summarizer.py 的 stage 模块风格——单一 async 函数，无工厂，无 Protocol。
后续接入其他厂商时再基于真实需求抽象。
"""
import base64
import json
import logging
import re
import uuid

import httpx

logger = logging.getLogger(__name__)

# ── 领域异常（由路由层映射到 HTTP 状态码） ──


class TtsError(Exception):
    """TTS 领域异常基类。"""


class TtsAuthError(TtsError):
    """豆包鉴权失败（401/403）。"""

    def __init__(self, message: str = "豆包鉴权失败，请检查 API Key 和 Resource ID"):
        self.message = message


class TtsUpstreamError(TtsError):
    """豆包服务返回错误（code > 0）。"""

    def __init__(self, message: str = "豆包服务返回错误"):
        self.message = message


class TtsTimeoutError(TtsError):
    """豆包语音合成超时。"""

    message: str = "豆包语音合成超时，请稍后重试"


# ── 豆包单向流式接口 ──

_URL = "https://openspeech.bytedance.com/api/v3/tts/unidirectional"
_MAX_TEXT_CHARS = 2000
_SOURCE_PATTERN = re.compile(r"\nsource:.*$", flags=re.IGNORECASE)


async def synthesize_speech(
    text: str,
    *,
    api_key: str,
    speaker: str,
    resource_id: str = "seed-tts-2.0",
) -> bytes:
    """将摘要文本合成为 MP3 音频字节。

    流程：
    1. 预处理：去 source: 尾注 → 长度截断 → 空文本校验
    2. httpx.stream("POST", ...) 流式请求
    3. 逐行 JSON → base64 拼音频 → 拼 bytearray
    4. 异常分类为 TtsAuthError / TtsUpstreamError / TtsTimeoutError
    """
    # ── 1. 预处理 ──
    clean = _SOURCE_PATTERN.sub("", text).strip()
    if not clean:
        raise TtsUpstreamError("摘要文本为空，无法合成语音")
    if len(clean) > _MAX_TEXT_CHARS:
        logger.warning("摘要文本过长（%d 字），截断到 %d 字", len(clean), _MAX_TEXT_CHARS)
        clean = clean[:_MAX_TEXT_CHARS]

    # ── 2. 请求 ──
    headers = {
        "X-Api-Key": api_key,
        "X-Api-Resource-Id": resource_id,
        "X-Api-Request-Id": str(uuid.uuid4()),
        "X-Control-Require-Usage-Tokens-Return": "*",
        "Content-Type": "application/json",
        "Connection": "keep-alive",
    }
    payload = {
        "req_params": {
            "text": clean,
            "speaker": speaker,
            "audio_params": {"format": "mp3", "sample_rate": 24000},
            "additions": json.dumps({"disable_markdown_filter": True}),
        }
    }

    timeout = httpx.Timeout(connect=10.0, read=60.0, write=10.0, pool=10.0)

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream("POST", _URL, headers=headers, json=payload) as response:
                # 先检查 HTTP 状态码
                try:
                    response.raise_for_status()
                except httpx.HTTPStatusError as e:
                    if e.response.status_code in (401, 403):
                        raise TtsAuthError()
                    raise TtsUpstreamError(f"豆包服务返回 HTTP {e.response.status_code}") from e

                # ── 3. 流式读取 ──
                audio_data = bytearray()
                async for line in response.aiter_lines():
                    if not line:
                        continue
                    try:
                        chunk = json.loads(line)
                    except json.JSONDecodeError:
                        logger.warning("豆包返回非 JSON 行，跳过")
                        continue

                    code = chunk.get("code", -1)
                    if code == 0:
                        data_b64 = chunk.get("data", "")
                        if data_b64:
                            audio_data.extend(base64.b64decode(data_b64))
                    elif code == 20000000:
                        break
                    elif code > 0:
                        msg = chunk.get("message", "未知错误")
                        raise TtsUpstreamError(f"豆包返回错误 (code={code}): {msg}")

                if not audio_data:
                    raise TtsUpstreamError("未收到音频数据，请检查音色 ID 或文本内容")
                return bytes(audio_data)

    except httpx.TimeoutException as e:
        raise TtsTimeoutError() from e
    except TtsError:
        raise
    except Exception as e:
        logger.error("TTS 请求异常: %s", e)
        raise TtsUpstreamError(f"语音合成失败: {e}") from e
