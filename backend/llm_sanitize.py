"""Remove common LLM meta / closing phrases from model output."""
from __future__ import annotations

import re
from typing import Optional

# Trailing blocks (English + Chinese) often added despite instructions
_PATTERNS = [
    re.compile(r"(?is)\n{1,2}let me know[\s\S]{0,800}\Z"),
    re.compile(r"(?is)\n{1,2}feel free to[\s\S]{0,800}\Z"),
    re.compile(r"(?is)\n{1,2}if you (?:need|have|would like)[\s\S]{0,800}\Z"),
    re.compile(r"(?is)\n{1,2}(?:happy to|please let me know|don't hesitate)[\s\S]{0,800}\Z"),
    re.compile(r"(?is)\n{1,2}(?:hope this helps|thanks for reading)[\s\S]{0,400}\Z"),
    re.compile(r"(?is)\n{1,2}(?:请告诉|如有需要|如需|欢迎反馈|希望对你|以上(?:内容)?)[\s\S]{0,800}\Z"),
]


def strip_llm_artifacts(text: Optional[str]) -> str:
    if not text or not isinstance(text, str):
        return (text or "").strip()
    t = text.strip()
    for _ in range(6):
        before = t
        for pat in _PATTERNS:
            t = pat.sub("", t).strip()
        if t == before:
            break
    lines = t.split("\n")
    while lines:
        last = lines[-1].strip()
        if not last:
            lines.pop()
            continue
        low = last.lower()
        if len(last) < 200 and any(
            x in low
            for x in (
                "let me know",
                "further adjustments",
                "feel free",
                "hope this helps",
                "请告诉我",
                "如需调整",
                "欢迎反馈",
            )
        ):
            lines.pop()
            continue
        break
    return "\n".join(lines).strip()


def extract_tagged(
    text: Optional[str],
    tag: str,
    *,
    fallback=strip_llm_artifacts,
) -> str:
    """白名单式提取：只取 <tag>…</tag> 之间的内容，标签外（前言/元信息/客套）一律丢弃。

    比起黑名单 strip_* 逐个匹配「不想要的」，白名单只认「想要的」，更难被绕过。
    - 正常闭合：取 <tag>…</tag> 内部
    - 仅有开标签（被 max_tokens 截断未闭合）：取开标签之后的全部内容
    - 完全没有标签（模型没遵守 / 不具备能力）：回退到 fallback 黑名单清洗
    """
    t = (text or "").strip()
    if not t:
        return ""
    closed = re.search(rf"(?is)<{tag}>(.*?)</{tag}>", t)
    if closed and closed.group(1).strip():
        return closed.group(1).strip()
    # 仅当根本没有闭合标签（被 max_tokens 截断）时才用开标签兜底，
    # 否则会把残留的 </tag> 一起捞出来。
    if not re.search(rf"(?is)</{tag}>", t):
        open_only = re.search(rf"(?is)<{tag}>(.*)\Z", t)
        if open_only and open_only.group(1).strip():
            return open_only.group(1).strip()
    return fallback(t) if fallback else t


# 转录优化输出里常见的「过程说明 / 思考 / 编辑备注」前缀
_TRANSCRIPT_LEADING_PATTERNS = [
    re.compile(
        r"(?is)^\s*(?:"
        r"以下是(?:优化|修正|整理)(?:后|过的)?(?:的)?(?:转录文本|转录|文本|内容)?[：:，,]?\s*"
        r"|(?:优化|修正)(?:后|过的)?(?:的)?(?:转录文本|转录|文本)(?:如下|如下所示)?[：:，,]?\s*"
        r"|Here is the optimized(?: transcript)?[：:,.]?\s*"
        r"|Optimized transcript[：:,.]?\s*"
        r"|Output[：:,.]?\s*"
        r")+"
    ),
    re.compile(r"(?is)^\s*#{1,6}\s*(?:优化(?:后|版)?|转录(?:文本)?|Transcript)\s*\n+"),
]

# 整行可丢弃的元信息行（过程分析、改动说明等）
_TRANSCRIPT_META_LINE = re.compile(
    r"(?is)^\s*(?:"
    r"(?:\*\*)?(?:分析|说明|备注|改动|编辑|思考|总结|解释|注释|提示)(?:\*\*)?[：:]"
    r"|(?:Note|Analysis|Changes?|Explanation|Summary|Editor'?s note)[：:.]"
    r"|^>\s*(?:注|说明|Note)"
    r"|\[(?:上文续|Context continued)[：:]"
    r")"
)

# reasoning / think 标签（部分模型会泄漏）
_THINK_BLOCK = re.compile(r"(?is)<think(?:ing)?>[\s\S]*?</think(?:ing)?>\s*")


def strip_transcript_optimization_output(text: Optional[str]) -> str:
    """移除转录优化阶段 LLM 偶发输出的过程分析、思考与编辑备注。"""
    t = strip_llm_artifacts(text)
    if not t:
        return ""

    t = _THINK_BLOCK.sub("", t).strip()

    for _ in range(4):
        before = t
        for pat in _TRANSCRIPT_LEADING_PATTERNS:
            t = pat.sub("", t).strip()
        if t == before:
            break

    lines = t.split("\n")
    cleaned: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            cleaned.append(line)
            continue
        if _TRANSCRIPT_META_LINE.match(stripped):
            continue
        # 跳过纯 markdown 小标题式的过程段（非正文）
        if re.match(r"^#{1,6}\s*(?:分析|说明|改动|优化说明|Output)", stripped, re.I):
            continue
        cleaned.append(line)

    t = "\n".join(cleaned).strip()
    t = re.sub(r"(?is)^[（(](?:注|说明|Note)[^）)]{0,200}[）)]\s*", "", t)
    t = re.sub(r"(?is)\s*[（(](?:注|说明|Note)[^）)]{0,200}[）)]\s*\Z", "", t)
    return t.strip()
