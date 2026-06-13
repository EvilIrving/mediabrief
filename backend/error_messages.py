"""错误信息翻译层：把底层 yt-dlp / ffmpeg / 网络的原始报错，
映射成普通用户看得懂、且可操作的中文提示。

设计目标（面向打包给小白的桌面应用）：
- 用户看到的不应是 "ERROR: Postprocessing: ... Invalid argument" 这类原始串；
- 而应是 "无法转换音频…" 并附带下一步怎么办。

用法：在任务失败、准备写入 task 的错误信息时调用 ``humanize_error(exc)``。
我们自己抛出的领域异常（exceptions.TranscriberError，如 LLMError）信息本就友好，
直接透传；只有第三方/系统原始错误才走签名匹配。
"""
from __future__ import annotations

import logging

from exceptions import TranscriberError

logger = logging.getLogger(__name__)

# (匹配片段（小写）, 友好提示) —— 顺序敏感，靠前的优先命中。
_SIGNATURES: list[tuple[str, str]] = [
    # ── 鉴权 / 反爬 ──
    ("sign in to confirm", "该来源要求登录验证（疑似风控）。可在设置中导入浏览器 Cookies 后重试。"),
    ("confirm you're not a bot", "该来源要求登录验证（疑似风控）。可在设置中导入浏览器 Cookies 后重试。"),
    ("login required", "该内容需要登录才能访问，请配置对应平台的 Cookies。"),
    ("this video is private", "该视频为私密视频，无法访问。"),
    ("members-only", "该内容为会员专享，需要登录的会员账号 Cookies 才能下载。"),
    ("age", "该内容有年龄限制，需要登录的账号 Cookies 才能访问。"),
    # ── 地区 / 可用性 ──
    ("requested format is not available", "无法获取该视频的可用格式，可能是地区限制、需要登录，或该来源暂不受支持。"),
    ("only images are available", "该链接只解析到图片，没有可下载的音视频内容。"),
    ("video unavailable", "该视频不可用，可能已被删除或设为私密。"),
    ("this video is not available", "该视频在当前地区不可用（地区限制）。"),
    ("geo", "该内容受地区限制，无法在当前网络环境访问。可尝试使用代理。"),
    ("404", "找不到该资源（链接可能已失效）。"),
    ("403", "访问被拒绝，可能是地区限制、需要登录或链接已过期。"),
    ("412", "访问被来源站点拦截，请稍后重试或更换链接。"),
    ("429", "请求过于频繁，被来源站点限流，请稍后再试。"),
    # ── 网络 ──
    ("unable to download webpage", "无法打开来源页面，请检查网络连接或链接是否正确。"),
    ("timed out", "网络连接超时，请检查网络或稍后重试。"),
    ("timeout", "网络连接超时，请检查网络或稍后重试。"),
    ("connection", "网络连接出错，请检查网络/代理后重试。"),
    ("name or service not known", "无法解析来源域名，请检查网络或链接是否正确。"),
    # ── ffmpeg 后处理 ──
    ("no decoder found", "内置 ffmpeg 缺少该音频编码的解码器，无法转换。请反馈此链接以便补充支持。"),
    ("postprocessing", "音频转换失败。该来源的音视频格式可能不受支持，请反馈此链接。"),
    ("ffmpeg", "音视频处理失败，请确认文件未损坏后重试。"),
    # ── 不支持 ──
    ("unsupported url", "暂不支持该网站的链接。"),
    ("no video formats found", "未能在该链接中找到可下载的音视频。"),
]


def humanize_error(exc: Exception) -> str:
    """把异常转换为面向用户的中文提示。

    - 领域异常（我们自己抛的，信息已友好）直接透传；
    - 第三方/系统原始错误按签名匹配；命中返回友好文案，未命中返回简短兜底
      并保留原始信息尾巴，便于用户反馈。
    """
    if isinstance(exc, TranscriberError):
        return str(exc)

    raw = str(exc).strip()
    low = raw.lower()
    for needle, friendly in _SIGNATURES:
        if needle in low:
            return friendly

    # 未命中：给通用提示，并附上截断的原始信息（方便用户复制反馈）。
    logger.info("未匹配的错误签名，原样保留: %s", raw[:300])
    snippet = raw if len(raw) <= 200 else raw[:200] + "…"
    return f"处理失败：{snippet}" if snippet else "处理失败，请稍后重试。"
