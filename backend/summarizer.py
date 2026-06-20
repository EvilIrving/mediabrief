import openai
import json
import logging
import re
from typing import Optional

from config import settings
from exceptions import LLMError
from llm_sanitize import (
    strip_llm_artifacts,
    strip_transcript_optimization_output,
    extract_tagged,
)
from prompts import transcript as transcript_prompts
from prompts import summary as summary_prompts

logger = logging.getLogger(__name__)

# 转录优化阶段的结构化输出 schema：只允许模型填「说话正文段落」，
# 元信息（检测语言/概率）、标题、改动说明等没有任何字段可放，从结构上杜绝泄漏。
_TRANSCRIPT_OPTIMIZE_SCHEMA = {
    "type": "object",
    "properties": {
        "paragraphs": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "Optimized transcript as spoken-content paragraphs only. "
                "No metadata, no headings, no language/probability lines, "
                "no commentary or editor notes."
            ),
        }
    },
    "required": ["paragraphs"],
    "additionalProperties": False,
}


def _raise_if_fatal_llm_error(exc: Exception) -> None:
    """鉴权/额度/连接/模型不存在等「配置类」错误直接抛 LLMError 浮到前端，
    给出可操作的中文提示，而非被静默吞成低质量兜底摘要。

    其余错误（如内容过长、偶发 5xx）返回 None，让调用方继续走兜底逻辑。
    对一个「填 API Key 即用」的应用，让用户第一时间看到「Key 错了/没额度/连不上」
    是最关键的体验。
    """
    msg = str(exc)
    auth = getattr(openai, "AuthenticationError", ())
    perm = getattr(openai, "PermissionDeniedError", ())
    rate = getattr(openai, "RateLimitError", ())
    notfound = getattr(openai, "NotFoundError", ())
    conn = (
        getattr(openai, "APIConnectionError", ()),
        getattr(openai, "APITimeoutError", ()),
    )
    if isinstance(exc, auth):
        raise LLMError("API Key 无效或已过期，请在设置中检查 API Key 是否正确。")
    if isinstance(exc, perm):
        raise LLMError("API Key 无权访问该模型，请检查模型权限，或更换可用的模型 ID。")
    # 402 / "Insufficient Balance"：部分 OpenAI 兼容服务（如 DeepSeek）用 402 表示余额耗尽，
    # SDK 不会映射成 RateLimitError，需按状态码与文案兜底识别，否则会被静默降级成简化摘要。
    status_code = getattr(exc, "status_code", None)
    if (
        isinstance(exc, rate)
        or status_code == 402
        or "insufficient_quota" in msg
        or "exceeded your current quota" in msg
        or "insufficient balance" in msg.lower()
    ):
        raise LLMError("请求受限或额度不足（余额/配额可能已耗尽），请检查账户余额或稍后再试。")
    if isinstance(exc, notfound):
        raise LLMError("模型不存在：请检查模型 ID 与 Base URL 是否匹配。")
    if isinstance(exc, conn):
        raise LLMError("无法连接到模型服务，请检查网络/代理，以及 Base URL 是否正确。")

class Summarizer:
    """文本总结器，使用OpenAI API生成多语言摘要"""
    
    def __init__(self, api_key: str = None, base_url: str = None, model: str = None):
        """
        初始化总结器。

        API Key、Base URL 和模型 ID 必须由前端 Settings 面板随请求传入；
        后端不再从环境变量或 .env 中读取 fallback。
        model 指定时会同时作为 fast_model 和 advanced_model 使用。
        """
        effective_key = (api_key or "").strip()
        effective_url = (base_url or "").strip().rstrip("/") or None
        effective_model = (model or "").strip()

        if not effective_key or not effective_model:
            logger.debug("未提供完整的前端模型配置，将无法使用摘要功能")
            self.client = None
        else:
            kwargs = {"api_key": effective_key}
            if effective_url:
                kwargs["base_url"] = effective_url
                logger.info(f"OpenAI客户端已初始化，base_url={effective_url}")
            else:
                logger.info("OpenAI客户端已初始化，使用默认端点")
            # 设置超时防止 LLM 调用无限期阻塞
            kwargs.setdefault("timeout", settings.llm_request_timeout_sec)
            kwargs.setdefault("max_retries", settings.llm_max_retries)
            self.client = openai.OpenAI(**kwargs)

        # 模型 ID 仅来自构造函数参数（前端 Settings）。
        self.fast_model = effective_model
        self.advanced_model = effective_model
        # LLM 总超时（兜底），集中在 config.settings 调整
        self._llm_timeout = settings.llm_timeout_sec
        
        # 支持的语言映射
        self.language_map = {
            "en": "English",
            "zh": "中文（简体）",
            "es": "Español",
            "fr": "Français", 
            "de": "Deutsch",
            "it": "Italiano",
            "pt": "Português",
            "ru": "Русский",
            "ja": "日本語",
            "ko": "한국어",
            "ar": "العربية"
        }
    
    def optimize_transcript(self, raw_transcript: str, video_title: Optional[str] = None) -> str:
        """
        优化转录文本：修正错别字，按含义分段
        支持长文本自动分块处理
        
        Args:
            raw_transcript: 原始转录文本
            video_title: 视频/播客标题（弱提示，供领域预分析参考）
            
        Returns:
            优化后的转录文本（Markdown格式）
        """
        try:
            if not self.client:
                logger.warning("OpenAI API不可用，返回原始转录")
                return raw_transcript

            # 预处理：仅移除时间戳与元信息，保留全部口语/重复内容
            preprocessed = self._remove_timestamps_and_meta(raw_transcript)
            domain_context = self._infer_transcript_domain(preprocessed, video_title)

            # 使用JS策略：按字符长度分块（更贴近tokens上限，避免估算误差）
            detected_lang_code = self._detect_transcript_language(preprocessed)
            max_chars_per_chunk = 4000  # 对齐JS：每块最大约4000字符

            if len(preprocessed) > max_chars_per_chunk:
                logger.info(f"文本较长({len(preprocessed)} chars)，启用分块优化")
                return self._format_long_transcript_in_chunks(
                    preprocessed, detected_lang_code, max_chars_per_chunk, domain_context
                )
            else:
                return self._format_single_chunk(preprocessed, detected_lang_code, domain_context)

        except Exception as e:
            logger.error(f"优化转录文本失败: {str(e)}")
            logger.info("返回原始转录文本")
            return raw_transcript

    def _sample_transcript_for_domain(self, text: str, max_chars: int = 5000) -> str:
        """取转录采样供领域预分析：短文全文，长文取开头+中间各一段。"""
        text = (text or "").strip()
        if len(text) <= max_chars:
            return text
        half = max_chars // 2
        head = text[:half]
        mid_start = max(0, len(text) // 2 - half // 2)
        tail = text[mid_start : mid_start + half]
        return f"{head}\n\n[...]\n\n{tail}"

    def _infer_transcript_domain(
        self, preprocessed: str, video_title: Optional[str] = None
    ) -> str:
        """预分析转录采样，生成简短的领域与纠偏约束（非完整 prompt）。"""
        if not self.client or not (preprocessed or "").strip():
            return ""
        sample = self._sample_transcript_for_domain(preprocessed)
        title_hint = ""
        if video_title and video_title.strip():
            title_hint = f"\n\n来源标题（仅供参考，可能不准确）：{video_title.strip()}"

        prompt = transcript_prompts.DOMAIN_INFER
        try:
            response = self.client.chat.completions.create(
                model=self.fast_model,
                messages=prompt.render(title_hint=title_hint, sample=sample),
                max_tokens=prompt.max_tokens,
                temperature=prompt.temperature,
            )
            brief = strip_llm_artifacts(response.choices[0].message.content or "").strip()
            if brief:
                logger.info(f"转录领域预分析完成，约束长度: {len(brief)}")
            return brief
        except Exception as e:
            logger.warning(f"转录领域预分析失败，跳过约束: {e}")
            return ""

    def _estimate_tokens(self, text: str) -> int:
        """
        改进的token数量估算算法
        更保守的估算，考虑系统prompt和格式化开销
        """
        # 更保守的估算：考虑实际使用中的token膨胀
        chinese_chars = sum(1 for char in text if '\u4e00' <= char <= '\u9fff')
        english_words = len([word for word in text.split() if word.isascii() and word.isalpha()])
        
        # 计算基础tokens
        base_tokens = chinese_chars * 1.5 + english_words * 1.3
        
        # 考虑markdown格式、时间戳等开销（约30%额外开销）
        format_overhead = len(text) * 0.15
        
        # 考虑系统prompt开销（约2000-3000 tokens）
        system_prompt_overhead = 2500
        
        total_estimated = int(base_tokens + format_overhead + system_prompt_overhead)
        
        return total_estimated


    # ===== JS openaiService.js 移植：分块/上下文/去重/格式化 =====

    def _ensure_markdown_paragraphs(self, text: str) -> str:
        """确保Markdown段落空行、标题后空行、压缩多余空行。"""
        if not text:
            return text
        formatted = text.replace("\r\n", "\n")
        import re
        # 标题后加空行
        formatted = re.sub(r"(^#{1,6}\s+.*)\n([^\n#])", r"\1\n\n\2", formatted, flags=re.M)
        # 压缩≥3个换行为2个
        formatted = re.sub(r"\n{3,}", "\n\n", formatted)
        # 去首尾空行
        formatted = re.sub(r"^\n+", "", formatted)
        formatted = re.sub(r"\n+$", "", formatted)
        return formatted

    def _format_single_chunk(
        self,
        chunk_text: str,
        transcript_language: str = 'zh',
        domain_context: str = "",
    ) -> str:
        """单块优化（修正+格式化），遵循4000 tokens 限制。"""
        # 领域约束作为可选上下文层；空串时在合并时被自动跳过。
        domain_block = (
            f"**领域与纠偏约束（预分析，仅供参考）：**\n{domain_context}"
            if domain_context
            else ""
        )
        prompt = (
            transcript_prompts.OPTIMIZE_ZH
            if transcript_language == 'zh'
            else transcript_prompts.OPTIMIZE_EN
        )
        messages = prompt.render(domain_block=domain_block, chunk_text=chunk_text)
        try:
            response = self._chat_optimize_with_schema(messages)
            choice = response.choices[0]
            optimized_text = self._extract_optimized_text(choice.message.content or "")
            # 空输出（finish_reason=length 截断 / 内容过滤 / reasoning 模型耗尽 tokens）视为失败，回退基础格式化
            if not optimized_text.strip():
                finish_reason = getattr(choice, "finish_reason", None)
                logger.warning(f"单块优化返回空内容(finish_reason={finish_reason})，回退到基础格式化")
                return self._apply_basic_formatting(chunk_text)
            # 移除诸如 "# Transcript" / "## Transcript" 等标题（schema 路径通常无此问题，纯文本回退路径仍需）
            optimized_text = self._remove_transcript_heading(optimized_text)
            enforced = self._enforce_paragraph_max_chars(optimized_text.strip(), max_chars=400)
            return self._ensure_markdown_paragraphs(enforced)
        except Exception as e:
            logger.error(f"单块文本优化失败: {e}")
            return self._apply_basic_formatting(chunk_text)

    def _chat_optimize_with_schema(self, messages: list):
        """优先以 json_schema 结构化输出调用；对不支持该特性的 OpenAI 兼容服务自动回退到纯文本。"""
        base_kwargs = dict(
            model=self.fast_model,
            messages=messages,
            max_tokens=8000,
            temperature=0.1,
        )
        try:
            return self.client.chat.completions.create(
                **base_kwargs,
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "optimized_transcript",
                        "strict": True,
                        "schema": _TRANSCRIPT_OPTIMIZE_SCHEMA,
                    },
                },
            )
        except Exception as e:
            # 仅当是「不支持 response_format/json_schema」类的请求参数错误时回退；
            # 鉴权/额度/连接等致命错误不在此吞掉，交由上层 except 统一处理。
            if not self._is_unsupported_schema_error(e):
                raise
            logger.info(f"模型不支持 json_schema 结构化输出，回退纯文本：{e}")
            return self.client.chat.completions.create(**base_kwargs)

    @staticmethod
    def _is_unsupported_schema_error(exc: Exception) -> bool:
        """判断异常是否为「服务端不支持 response_format/json_schema」的可回退错误。"""
        badreq = getattr(openai, "BadRequestError", ())
        unprocessable = getattr(openai, "UnprocessableEntityError", ())
        if not isinstance(exc, (badreq, unprocessable)):
            # 部分兼容服务用 404/NotFound 表示不认识该参数
            notfound = getattr(openai, "NotFoundError", ())
            if not isinstance(exc, notfound):
                return False
        msg = str(exc).lower()
        return any(
            kw in msg
            for kw in ("response_format", "json_schema", "json schema", "structured output")
        )

    def _extract_optimized_text(self, raw: str) -> str:
        """白名单式提取优化输出，按三级降级：
        1. json_schema 路径：{"paragraphs": [...]} → 段落拼接
        2. 标签路径：取 <transcript>…</transcript> 内的内容（标签外一律丢弃）
        3. 兜底：旧的黑名单清洗（不支持前两者的服务）
        """
        text = (raw or "").strip()
        if not text:
            return ""

        # 1. schema：合法 JSON 且含 paragraphs 数组
        try:
            data = json.loads(text)
        except (ValueError, TypeError):
            data = None
        if isinstance(data, dict) and isinstance(data.get("paragraphs"), list):
            paragraphs = [str(p).strip() for p in data["paragraphs"] if str(p).strip()]
            return "\n\n".join(paragraphs)

        # 2. 标签：只取 <transcript> 内的内容；标签外（含检测语言等元信息）整体丢弃
        #    无标签时回退到 3. 旧清洗逻辑
        return extract_tagged(text, "transcript", fallback=strip_transcript_optimization_output)

    def _smart_split_long_chunk(self, text: str, max_chars_per_chunk: int) -> list:
        """在句子/空格边界处安全切分超长文本。"""
        chunks = []
        pos = 0
        while pos < len(text):
            end = min(pos + max_chars_per_chunk, len(text))
            if end < len(text):
                # 优先句子边界
                sentence_endings = ['。', '！', '？', '.', '!', '?']
                best = -1
                for ch in sentence_endings:
                    idx = text.rfind(ch, pos, end)
                    if idx > best:
                        best = idx
                if best > pos + int(max_chars_per_chunk * 0.7):
                    end = best + 1
                else:
                    # 次选：空格边界
                    space_idx = text.rfind(' ', pos, end)
                    if space_idx > pos + int(max_chars_per_chunk * 0.8):
                        end = space_idx
            chunks.append(text[pos:end].strip())
            pos = end
        return [c for c in chunks if c]

    def _find_safe_cut_point(self, text: str) -> int:
        """找到安全的切割点（段落>句子>短语）。"""
        import re
        # 段落
        p = text.rfind("\n\n")
        if p > 0:
            return p + 2
        # 句子
        last_sentence_end = -1
        for m in re.finditer(r"[。！？\.!?]\s*", text):
            last_sentence_end = m.end()
        if last_sentence_end > 20:
            return last_sentence_end
        # 短语
        last_phrase_end = -1
        for m in re.finditer(r"[，；,;]\s*", text):
            last_phrase_end = m.end()
        if last_phrase_end > 20:
            return last_phrase_end
        return len(text)

    def _find_overlap_between_texts(self, text1: str, text2: str) -> str:
        """检测相邻两段的重叠内容，用于去重。"""
        max_len = min(len(text1), len(text2))
        # 逐步从长到短尝试
        for length in range(max_len, 19, -1):
            suffix = text1[-length:]
            prefix = text2[:length]
            if suffix == prefix:
                cut = self._find_safe_cut_point(prefix)
                if cut > 20:
                    return prefix[:cut]
                return suffix
        return ""

    def _split_sentences(self, text: str) -> list:
        """按句子结束符切分文本，保留标点。"""
        import re
        parts = re.split(r"([。！？\.!?]+\s*)", text)
        sentences = []
        buf = ""
        for i, part in enumerate(parts):
            if i % 2 == 0:
                buf += part
            else:
                buf += part
                if buf.strip():
                    sentences.append(buf.strip())
                    buf = ""
        if buf.strip():
            sentences.append(buf.strip())
        return sentences

    def _apply_basic_formatting(self, text: str) -> str:
        """当AI失败时的回退：按句子拼段，段落≤250字符，双换行分隔。"""
        if not text or not text.strip():
            return text
        sentences = self._split_sentences(text)
        paras = []
        cur = ""
        sentence_count = 0
        for s in sentences:
            candidate = (cur + " " + s).strip() if cur else s
            sentence_count += 1
            # 改进的分段逻辑：考虑句子数量和长度
            should_break = False
            if len(candidate) > 400 and cur:  # 段落过长
                should_break = True
            elif len(candidate) > 200 and sentence_count >= 3:  # 中等长度且句子数足够
                should_break = True
            elif sentence_count >= 6:  # 句子数过多
                should_break = True
            
            if should_break:
                paras.append(cur.strip())
                cur = s
                sentence_count = 1
            else:
                cur = candidate
        if cur.strip():
            paras.append(cur.strip())
        return self._ensure_markdown_paragraphs("\n\n".join(paras))

    def _format_long_transcript_in_chunks(
        self,
        raw_transcript: str,
        transcript_language: str,
        max_chars_per_chunk: int,
        domain_context: str = "",
    ) -> str:
        """智能分块+上下文+去重 合成优化文本（JS策略移植）。"""
        import re
        # 先按句子切分，组装不超过max_chars_per_chunk的块
        sentences = self._split_sentences(raw_transcript)

        chunks = []
        cur = ""
        for s in sentences:
            candidate = (cur + " " + s).strip() if cur else s
            if len(candidate) > max_chars_per_chunk and cur:
                chunks.append(cur.strip())
                cur = s
            else:
                cur = candidate
        if cur.strip():
            chunks.append(cur.strip())

        # 对仍然过长的块二次安全切分
        final_chunks = []
        for c in chunks:
            if len(c) <= max_chars_per_chunk:
                final_chunks.append(c)
            else:
                final_chunks.extend(self._smart_split_long_chunk(c, max_chars_per_chunk))

        logger.info(f"文本分为 {len(final_chunks)} 块处理")

        optimized = []
        for i, c in enumerate(final_chunks):
            chunk_with_context = c
            if i > 0:
                prev_tail = final_chunks[i - 1][-100:]
                marker = f"[上文续：{prev_tail}]" if transcript_language == 'zh' else f"[Context continued: {prev_tail}]"
                chunk_with_context = marker + "\n\n" + c
            try:
                oc = self._format_single_chunk(chunk_with_context, transcript_language, domain_context)
                # 移除上下文标记
                oc = re.sub(r"^\[(上文续|Context continued)：?:?.*?\]\s*", "", oc, flags=re.S)
                optimized.append(oc)
            except Exception as e:
                logger.warning(f"第 {i+1} 块优化失败，使用基础格式化: {e}")
                optimized.append(self._apply_basic_formatting(c))

        # 邻接块去重
        deduped = []
        for i, c in enumerate(optimized):
            cur_txt = c
            if i > 0 and deduped:
                prev = deduped[-1]
                overlap = self._find_overlap_between_texts(prev[-200:], cur_txt[:200])
                if overlap:
                    cur_txt = cur_txt[len(overlap):].lstrip()
                    if not cur_txt:
                        continue
            if cur_txt.strip():
                deduped.append(cur_txt)

        merged = "\n\n".join(deduped)
        merged = self._remove_transcript_heading(merged)
        enforced = self._enforce_paragraph_max_chars(merged, max_chars=400)
        return self._ensure_markdown_paragraphs(enforced)

    def _remove_timestamps_and_meta(self, text: str) -> str:
        """仅移除时间戳行与明显元信息（标题、检测语言等），保留原文口语/重复。"""
        lines = text.split('\n')
        kept = []
        for line in lines:
            s = line.strip()
            # 跳过时间戳与元信息
            if (s.startswith('**[') and s.endswith(']**')):
                continue
            if s.startswith('# '):
                # 跳过顶级标题（通常是视频标题，可在最终加回）
                continue
            # 实际写入的语言元信息是英文标签（transcriber.py / video_processor.py），
            # 中文标签为历史兼容；两者都需剔除，否则会原样混入正文。
            if (
                s.startswith('**检测语言:**')
                or s.startswith('**语言概率:**')
                or s.startswith('**Detected Language:**')
                or s.startswith('**Language Probability:**')
            ):
                continue
            # Whisper 转录正文标题（## Transcription Content）也是元信息，非口语内容
            if s in ('## Transcription Content', '## 转录内容'):
                continue
            kept.append(line)
        # 规范空行
        cleaned = '\n'.join(kept)
        return cleaned

    def _enforce_paragraph_max_chars(self, text: str, max_chars: int = 400) -> str:
        """按段落拆分并确保每段不超过max_chars，必要时按句子边界拆为多段。"""
        if not text:
            return text
        import re
        paragraphs = [p for p in re.split(r"\n\s*\n", text) if p is not None]
        new_paragraphs = []
        for para in paragraphs:
            para = para.strip()
            if len(para) <= max_chars:
                new_paragraphs.append(para)
                continue
            # 句子切分
            sentences = self._split_sentences(para)
            cur = ""
            for s in sentences:
                candidate = (cur + (" " if cur else "") + s).strip()
                if len(candidate) > max_chars and cur:
                    new_paragraphs.append(cur)
                    cur = s
                else:
                    cur = candidate
            if cur:
                new_paragraphs.append(cur)
        return "\n\n".join([p.strip() for p in new_paragraphs if p is not None])

    def _remove_transcript_heading(self, text: str) -> str:
        """移除开头或段落中的以 Transcript 为标题的行（任意级别#），不改变正文。"""
        if not text:
            return text
        import re
        # 移除形如 '## Transcript'、'# Transcript Text'、'### transcript' 的标题行
        lines = text.split('\n')
        filtered = []
        for line in lines:
            stripped = line.strip()
            if re.match(
                r"^#{1,6}\s*(?:transcript|优化|转录|transcription)(\s|\Z)",
                stripped,
                flags=re.I,
            ):
                continue
            filtered.append(line)
        return '\n'.join(filtered)

    def summarize(self, transcript: str, target_language: str = "zh", video_title: str = None) -> str:
        """
        生成视频转录的摘要（单步固定prompt模式）
        """
        try:
            if not self.client:
                logger.warning("OpenAI API不可用，生成备用摘要")
                return self._generate_fallback_summary(transcript, target_language, video_title)

            estimated_tokens = self._estimate_tokens(transcript)
            max_summarize_tokens = 4000

            if estimated_tokens <= max_summarize_tokens:
                return self._summarize_single_text(transcript, target_language, video_title)
            else:
                logger.info(f"文本较长({estimated_tokens} tokens)，启用分块摘要")
                return self._summarize_with_chunks(transcript, target_language, video_title, max_summarize_tokens)

        except Exception as e:
            _raise_if_fatal_llm_error(e)
            logger.error(f"生成摘要失败: {str(e)}")
            return self._generate_fallback_summary(transcript, target_language, video_title)

    def summary_two_step(
        self, transcript: str, target_language: str = "zh", video_title: str = None
    ) -> dict:
        """
        双步摘要：第一步LLM阅读内容生成定制化摘要Prompt，第二步用该Prompt生成最终摘要。
        返回 {"summary": str, "prompt": str}，其中prompt是第一步产出的定制化prompt。
        """
        try:
            if not self.client:
                logger.warning("OpenAI API不可用")
                fallback = self._generate_fallback_summary(transcript, target_language, video_title)
                return {"summary": fallback, "prompt": ""}

            language_name = self.language_map.get(target_language, "中文（简体）")

            # ── 第一步：阅读内容，生成定制化摘要Prompt ──────────────────────
            logger.info(f"双步摘要 Step 1: 生成定制化摘要Prompt ({language_name})")

            # Step 1 用于分析内容类型与摘要策略。5万字符以内不截断；超过则取前5万字符。
            preview_limit = 50000
            preview = transcript[:preview_limit] if len(transcript) > preview_limit else transcript

            step1 = summary_prompts.TWO_STEP_1
            resp1 = self.client.chat.completions.create(
                model=self.advanced_model,
                messages=step1.render(language_name=language_name, preview=preview),
                max_tokens=step1.max_tokens,
                temperature=step1.temperature,
            )
            custom_prompt = strip_llm_artifacts(resp1.choices[0].message.content or "")
            logger.info(f"双步摘要 Step 1 完成，Prompt长度: {len(custom_prompt)}")

            # ── 第二步：基于定制化Prompt生成最终摘要 ──────────────────────
            logger.info(f"双步摘要 Step 2: 基于定制Prompt生成摘要")

            # 摘要阶段使用完整输入。大上下文模型可以直接阅读长访谈；
            # streaming 只影响返回方式，不影响这里的上下文容量。
            transcript_for_summary = transcript

            step2 = summary_prompts.TWO_STEP_2
            resp2 = self.client.chat.completions.create(
                model=self.advanced_model,
                messages=step2.render(
                    custom_prompt=custom_prompt,
                    language_name=language_name,
                    transcript_for_summary=transcript_for_summary,
                ),
                max_tokens=step2.max_tokens,
                temperature=step2.temperature,
            )
            summary = extract_tagged(resp2.choices[0].message.content or "", "summary")
            logger.info(f"双步摘要 Step 2 完成，摘要长度: {len(summary)}")

            # 空摘要（截断/过滤/reasoning 耗尽 tokens）视为失败，回退到单步摘要
            if not summary.strip():
                finish_reason = getattr(resp2.choices[0], "finish_reason", None)
                logger.warning(f"双步摘要 Step 2 返回空(finish_reason={finish_reason})，回退到单步摘要")
                fallback = self.summarize(transcript, target_language, video_title)
                return {"summary": fallback, "prompt": custom_prompt}

            return {
                "summary": self._format_summary_with_meta(summary, target_language, video_title),
                "prompt": custom_prompt,
            }

        except Exception as e:
            _raise_if_fatal_llm_error(e)
            logger.error(f"双步摘要失败: {e}，回退到单步摘要")
            fallback = self.summarize(transcript, target_language, video_title)
            return {"summary": fallback, "prompt": "(双步摘要回退，使用默认prompt)"}

    def _summarize_single_text(self, transcript: str, target_language: str, video_title: str = None) -> str:
        """
        对单个文本进行摘要
        """
        # 获取目标语言名称
        language_name = self.language_map.get(target_language, "中文（简体）")
        
        logger.info(f"正在生成{language_name}摘要...")

        # 调用OpenAI API
        prompt = summary_prompts.SINGLE
        response = self.client.chat.completions.create(
            model=self.advanced_model,
            messages=prompt.render(language_name=language_name, transcript=transcript),
            max_tokens=prompt.max_tokens,
            temperature=prompt.temperature,
        )
        
        summary = extract_tagged(response.choices[0].message.content or "", "summary")

        # 空摘要视为失败，回退到备用摘要（避免最终写出空文件）
        if not summary.strip():
            finish_reason = getattr(response.choices[0], "finish_reason", None)
            logger.warning(f"单步摘要返回空(finish_reason={finish_reason})，使用备用摘要")
            return self._generate_fallback_summary(transcript, target_language, video_title)

        return self._format_summary_with_meta(summary, target_language, video_title)

    def _summarize_with_chunks(self, transcript: str, target_language: str, video_title: str, max_tokens: int) -> str:
        """
        分块摘要长文本
        """
        language_name = self.language_map.get(target_language, "中文（简体）")

        # 使用JS策略：按字符进行智能分块（段落>句子）
        chunks = self._smart_chunk_text(transcript, max_chars_per_chunk=4000)
        logger.info(f"分割为 {len(chunks)} 个块进行摘要")
        
        chunk_summaries = []
        
        # 每块生成局部摘要
        for i, chunk in enumerate(chunks):
            logger.info(f"正在摘要第 {i+1}/{len(chunks)} 块...")
            
            prompt = summary_prompts.CHUNK
            try:
                response = self.client.chat.completions.create(
                    model=self.advanced_model,
                    messages=prompt.render(
                        language_name=language_name,
                        part=i + 1,
                        total=len(chunks),
                        chunk=chunk,
                    ),
                    max_tokens=prompt.max_tokens,
                    temperature=prompt.temperature,
                )
                
                chunk_summary = extract_tagged(response.choices[0].message.content or "", "summary")
                # 空块摘要视为失败，用截断原文兜底，避免整体摘要塌缩为空
                if not chunk_summary.strip():
                    logger.warning(f"第 {i+1} 块摘要返回空，使用原文片段兜底")
                    chunk_summary = f"第{i+1}部分内容概述：" + chunk[:200] + "..."
                chunk_summaries.append(chunk_summary)

            except Exception as e:
                _raise_if_fatal_llm_error(e)
                logger.error(f"摘要第 {i+1} 块失败: {e}")
                # 失败时生成简单摘要
                simple_summary = f"第{i+1}部分内容概述：" + chunk[:200] + "..."
                chunk_summaries.append(simple_summary)
        
        # 合并所有局部摘要（带编号），如分块较多则分层整合（不引入小标题）
        combined_summaries = "\n\n".join([f"[Part {idx+1}]\n" + s for idx, s in enumerate(chunk_summaries)])

        logger.info("正在整合最终摘要...")
        if len(chunk_summaries) > 10:
            final_summary = self._integrate_hierarchical_summaries(chunk_summaries, target_language)
        else:
            final_summary = self._integrate_chunk_summaries(combined_summaries, target_language)

        return self._format_summary_with_meta(final_summary, target_language, video_title)

    def _smart_chunk_text(self, text: str, max_chars_per_chunk: int = 3500) -> list:
        """智能分块（先段落后句子），按字符上限切分。"""
        chunks = []
        paragraphs = [p for p in text.split('\n\n') if p.strip()]
        cur = ""
        for p in paragraphs:
            candidate = (cur + "\n\n" + p).strip() if cur else p
            if len(candidate) > max_chars_per_chunk and cur:
                chunks.append(cur.strip())
                cur = p
            else:
                cur = candidate
        if cur.strip():
            chunks.append(cur.strip())

        # 二次按句子切分过长块
        import re
        final_chunks = []
        for c in chunks:
            if len(c) <= max_chars_per_chunk:
                final_chunks.append(c)
            else:
                sentences = [s.strip() for s in re.split(r"[。！？\.!?]+", c) if s.strip()]
                scur = ""
                for s in sentences:
                    candidate = (scur + '。' + s).strip() if scur else s
                    if len(candidate) > max_chars_per_chunk and scur:
                        final_chunks.append(scur.strip())
                        scur = s
                    else:
                        scur = candidate
                if scur.strip():
                    final_chunks.append(scur.strip())
        return final_chunks

    def _integrate_hierarchical_summaries(
        self, chunk_summaries: list, target_language: str
    ) -> str:
        """Many partial summaries: fold through the same integrator as the <=10 case."""
        combined = "\n\n".join(
            f"[Part {idx + 1}]\n{s}" for idx, s in enumerate(chunk_summaries)
        )
        return self._integrate_chunk_summaries(combined, target_language)

    def _integrate_chunk_summaries(self, combined_summaries: str, target_language: str) -> str:
        """
        整合分块摘要为最终连贯摘要
        """
        language_name = self.language_map.get(target_language, "中文（简体）")
        
        try:
            prompt = summary_prompts.INTEGRATE
            response = self.client.chat.completions.create(
                model=self.advanced_model,
                messages=prompt.render(
                    language_name=language_name,
                    combined_summaries=combined_summaries,
                ),
                max_tokens=prompt.max_tokens,
                temperature=prompt.temperature,
            )

            integrated = extract_tagged(response.choices[0].message.content or "", "summary")
            # 空整合结果视为失败，直接合并各分块摘要
            if not integrated.strip():
                logger.warning("整合摘要返回空，直接合并分块摘要")
                return combined_summaries
            return integrated
        except Exception as e:
            logger.error(f"整合摘要失败: {e}")
            # 失败时直接合并
            return combined_summaries

    def _format_summary_with_meta(self, summary: str, target_language: str, video_title: str = None) -> str:
        """
        为摘要添加标题和元信息
        """
        language_name = self.language_map.get(target_language, "中文（简体）")
        meta_labels = self._get_summary_labels(target_language)
        
        # 不加任何小标题/免责声明，可保留视频标题作为一级标题
        if video_title:
            prefix = f"# {video_title}\n\n"
        else:
            prefix = ""
        return prefix + summary

    def _generate_fallback_summary(self, transcript: str, target_language: str, video_title: str = None) -> str:
        """
        生成备用摘要（当OpenAI API不可用时）
        
        Args:
            transcript: 转录文本
            video_title: 视频标题
            target_language: 目标语言代码
            
        Returns:
            备用摘要文本
        """
        language_name = self.language_map.get(target_language, "中文（简体）")
        
        # 简单的文本处理，提取关键信息
        lines = transcript.split('\n')
        content_lines = [line for line in lines if line.strip() and not line.startswith('#') and not line.startswith('**')]
        
        # 计算大概的长度
        total_chars = sum(len(line) for line in content_lines)
        
        # 使用目标语言的标签
        meta_labels = self._get_summary_labels(target_language)
        fallback_labels = self._get_fallback_labels(target_language)
        
        # 直接使用视频标题作为主标题  
        title = video_title if video_title else "Summary"
        
        summary = f"""# {title}

**{meta_labels['language_label']}:** {language_name}
**{fallback_labels['notice']}:** {fallback_labels['api_unavailable']}



## {fallback_labels['overview_title']}

**{fallback_labels['content_length']}:** {fallback_labels['about']} {total_chars} {fallback_labels['characters']}
**{fallback_labels['paragraph_count']}:** {len(content_lines)} {fallback_labels['paragraphs']}

## {fallback_labels['main_content']}

{fallback_labels['content_description']}

{fallback_labels['suggestions_intro']}

1. {fallback_labels['suggestion_1']}
2. {fallback_labels['suggestion_2']}
3. {fallback_labels['suggestion_3']}

## {fallback_labels['recommendations']}

- {fallback_labels['recommendation_1']}
- {fallback_labels['recommendation_2']}


<br/>

<p style="color: #888; font-style: italic; text-align: center; margin-top: 16px;"><em>{fallback_labels['fallback_disclaimer']}</em></p>"""
        
        return summary
    
    def _get_current_time(self) -> str:
        """获取当前时间字符串"""
        from datetime import datetime
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    def get_supported_languages(self) -> dict:
        """
        获取支持的语言列表
        
        Returns:
            语言代码到语言名称的映射
        """
        return self.language_map.copy()
    
    def _detect_transcript_language(self, transcript: str) -> str:
        """
        检测转录文本的主要语言
        
        Args:
            transcript: 转录文本
            
        Returns:
            检测到的语言代码
        """
        # 简单的语言检测逻辑：查找转录文本中的语言标记
        if "**检测语言:**" in transcript:
            # 从Whisper转录中提取检测到的语言
            lines = transcript.split('\n')
            for line in lines:
                if "**检测语言:**" in line:
                    # 提取语言代码，例如: "**检测语言:** en"
                    lang = line.split(":")[-1].strip()
                    return lang
        
        # 如果没有找到语言标记，使用简单的字符检测
        # 计算英文字符、中文字符等的比例
        total_chars = len(transcript)
        if total_chars == 0:
            return "en"  # 默认英文
            
        # 统计中文字符
        chinese_chars = sum(1 for char in transcript if '\u4e00' <= char <= '\u9fff')
        chinese_ratio = chinese_chars / total_chars
        
        # 统计英文字母
        english_chars = sum(1 for char in transcript if char.isascii() and char.isalpha())
        english_ratio = english_chars / total_chars
        
        # 根据比例判断
        if chinese_ratio > 0.3:
            return "zh"
        elif english_ratio > 0.3:
            return "en"
        else:
            return "en"  # 默认英文
    
    def _get_language_instruction(self, lang_code: str) -> str:
        """
        根据语言代码获取优化指令中使用的语言名称
        
        Args:
            lang_code: 语言代码
            
        Returns:
            语言名称
        """
        language_instructions = {
            "en": "English",
            "zh": "中文",
            "ja": "日本語",
            "ko": "한국어",
            "es": "Español",
            "fr": "Français",
            "de": "Deutsch",
            "it": "Italiano",
            "pt": "Português",
            "ru": "Русский",
            "ar": "العربية"
        }
        return language_instructions.get(lang_code, "English")
    

    def _get_summary_labels(self, lang_code: str) -> dict:
        """
        获取摘要页面的多语言标签
        
        Args:
            lang_code: 语言代码
            
        Returns:
            标签字典
        """
        labels = {
            "en": {
                "language_label": "Summary Language",
                "disclaimer": "This summary is automatically generated by AI for reference only"
            },
            "zh": {
                "language_label": "摘要语言",
                "disclaimer": "本摘要由AI自动生成，仅供参考"
            },
            "ja": {
                "language_label": "要約言語",
                "disclaimer": "この要約はAIによって自動生成されており、参考用です"
            },
            "ko": {
                "language_label": "요약 언어",
                "disclaimer": "이 요약은 AI에 의해 자동 생성되었으며 참고용입니다"
            },
            "es": {
                "language_label": "Idioma del Resumen",
                "disclaimer": "Este resumen es generado automáticamente por IA, solo para referencia"
            },
            "fr": {
                "language_label": "Langue du Résumé",
                "disclaimer": "Ce résumé est généré automatiquement par IA, à titre de référence uniquement"
            },
            "de": {
                "language_label": "Zusammenfassungssprache",
                "disclaimer": "Diese Zusammenfassung wird automatisch von KI generiert, nur zur Referenz"
            },
            "it": {
                "language_label": "Lingua del Riassunto",
                "disclaimer": "Questo riassunto è generato automaticamente dall'IA, solo per riferimento"
            },
            "pt": {
                "language_label": "Idioma do Resumo",
                "disclaimer": "Este resumo é gerado automaticamente por IA, apenas para referência"
            },
            "ru": {
                "language_label": "Язык резюме",
                "disclaimer": "Это резюме автоматически генерируется ИИ, только для справки"
            },
            "ar": {
                "language_label": "لغة الملخص",
                "disclaimer": "هذا الملخص تم إنشاؤه تلقائياً بواسطة الذكاء الاصطناعي، للمرجع فقط"
            }
        }
        return labels.get(lang_code, labels["en"])
    
    def _get_fallback_labels(self, lang_code: str) -> dict:
        """
        获取备用摘要的多语言标签
        
        Args:
            lang_code: 语言代码
            
        Returns:
            标签字典
        """
        labels = {
            "en": {
                "notice": "Notice",
                "api_unavailable": "OpenAI API is unavailable, this is a simplified summary",
                "overview_title": "Transcript Overview",
                "content_length": "Content Length",
                "about": "About",
                "characters": "characters",
                "paragraph_count": "Paragraph Count",
                "paragraphs": "paragraphs",
                "main_content": "Main Content",
                "content_description": "The transcript contains complete video speech content. Since AI summary cannot be generated currently, we recommend:",
                "suggestions_intro": "For detailed information, we suggest you:",
                "suggestion_1": "Review the complete transcript text for detailed information",
                "suggestion_2": "Focus on important paragraphs marked with timestamps",
                "suggestion_3": "Manually extract key points and takeaways",
                "recommendations": "Recommendations",
                "recommendation_1": "Configure OpenAI API key for better summary functionality",
                "recommendation_2": "Or use other AI services for text summarization",
                "fallback_disclaimer": "This is an automatically generated fallback summary"
            },
            "zh": {
                "notice": "注意",
                "api_unavailable": "由于OpenAI API不可用，这是一个简化的摘要",
                "overview_title": "转录概览",
                "content_length": "内容长度",
                "about": "约",
                "characters": "字符",
                "paragraph_count": "段落数量",
                "paragraphs": "段",
                "main_content": "主要内容",
                "content_description": "转录文本包含了完整的视频语音内容。由于当前无法生成智能摘要，建议您：",
                "suggestions_intro": "为获取详细信息，建议您：",
                "suggestion_1": "查看完整的转录文本以获取详细信息",
                "suggestion_2": "关注时间戳标记的重要段落",
                "suggestion_3": "手动提取关键观点和要点",
                "recommendations": "建议",
                "recommendation_1": "配置OpenAI API密钥以获得更好的摘要功能",
                "recommendation_2": "或者使用其他AI服务进行文本总结",
                "fallback_disclaimer": "本摘要为自动生成的备用版本"
            }
        }
        return labels.get(lang_code, labels["en"])
    
    def is_available(self) -> bool:
        """
        检查摘要服务是否可用
        
        Returns:
            True if OpenAI API is configured, False otherwise
        """
        return self.client is not None
