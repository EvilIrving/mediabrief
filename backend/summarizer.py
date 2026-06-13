import openai
import logging
from typing import Optional

from config import settings
from llm_sanitize import strip_llm_artifacts

logger = logging.getLogger(__name__)

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
    
    def optimize_transcript(self, raw_transcript: str) -> str:
        """
        优化转录文本：修正错别字，按含义分段
        支持长文本自动分块处理
        
        Args:
            raw_transcript: 原始转录文本
            
        Returns:
            优化后的转录文本（Markdown格式）
        """
        try:
            if not self.client:
                logger.warning("OpenAI API不可用，返回原始转录")
                return raw_transcript

            # 预处理：仅移除时间戳与元信息，保留全部口语/重复内容
            preprocessed = self._remove_timestamps_and_meta(raw_transcript)
            # 使用JS策略：按字符长度分块（更贴近tokens上限，避免估算误差）
            detected_lang_code = self._detect_transcript_language(preprocessed)
            max_chars_per_chunk = 4000  # 对齐JS：每块最大约4000字符

            if len(preprocessed) > max_chars_per_chunk:
                logger.info(f"文本较长({len(preprocessed)} chars)，启用分块优化")
                return self._format_long_transcript_in_chunks(preprocessed, detected_lang_code, max_chars_per_chunk)
            else:
                return self._format_single_chunk(preprocessed, detected_lang_code)

        except Exception as e:
            logger.error(f"优化转录文本失败: {str(e)}")
            logger.info("返回原始转录文本")
            return raw_transcript

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

    def _format_single_chunk(self, chunk_text: str, transcript_language: str = 'zh') -> str:
        """单块优化（修正+格式化），遵循4000 tokens 限制。"""
        # 构建与JS版一致的系统/用户提示
        if transcript_language == 'zh':
            prompt = (
                "请对以下音频转录文本进行智能优化和格式化，要求：\n\n"
                "**内容优化（正确性优先）：**\n"
                "1. 错误修正（转录错误/错别字/同音字/专有名词）\n"
                "2. 适度改善语法，补全不完整句子，保持原意和语言不变\n"
                "3. 口语处理：保留自然口语与重复表达，不要删减内容，仅添加必要标点\n"
                "4. **绝对不要改变人称代词（I/我、you/你等）和说话者视角**\n\n"
                "**分段规则：**\n"
                "- 按主题和逻辑含义分段，每段包含1-8个相关句子\n"
                "- 单段长度不超过400字符\n"
                "- 避免过多的短段落，合并相关内容\n\n"
                "**格式要求：**Markdown 段落，段落间空行\n\n"
                f"原始转录文本：\n{chunk_text}"
            )
            system_prompt = (
                "你是专业的音频转录文本优化助手，修正错误、改善通顺度和排版格式，"
                "必须保持原意，不得删减口语/重复/细节；仅移除时间戳或元信息。"
                "绝对不要改变人称代词或说话者视角。这可能是访谈对话，访谈者用'you'，被访者用'I/we'。"
            )
        else:
            prompt = (
                "Please intelligently optimize and format the following audio transcript text:\n\n"
                "Content Optimization (Accuracy First):\n"
                "1. Error Correction (typos, homophones, proper nouns)\n"
                "2. Moderate grammar improvement, complete incomplete sentences, keep original language/meaning\n"
                "3. Speech processing: keep natural fillers and repetitions, do NOT remove content; only add punctuation if needed\n"
                "4. **NEVER change pronouns (I, you, he, she, etc.) or speaker perspective**\n\n"
                "Segmentation Rules: Group 1-8 related sentences per paragraph by topic/logic; paragraph length NOT exceed 400 characters; avoid too many short paragraphs\n\n"
                "Format: Markdown paragraphs with blank lines between paragraphs\n\n"
                f"Original transcript text:\n{chunk_text}"
            )
            system_prompt = (
                "You are a professional transcript formatting assistant. Fix errors and improve fluency "
                "without changing meaning or removing any content; only timestamps/meta may be removed; keep Markdown paragraphs with blank lines. "
                "NEVER change pronouns or speaker perspective. This may be an interview: interviewer uses 'you', interviewee uses 'I/we'."
            )

        try:
            response = self.client.chat.completions.create(
                model=self.fast_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=4000,  # 对齐JS：优化/格式化阶段最大tokens≈4000
                temperature=0.1
            )
            optimized_text = strip_llm_artifacts(response.choices[0].message.content or "")
            # 空输出（finish_reason=length 截断 / 内容过滤 / reasoning 模型耗尽 tokens）视为失败，回退基础格式化
            if not optimized_text.strip():
                finish_reason = getattr(response.choices[0], "finish_reason", None)
                logger.warning(f"单块优化返回空内容(finish_reason={finish_reason})，回退到基础格式化")
                return self._apply_basic_formatting(chunk_text)
            # 移除诸如 "# Transcript" / "## Transcript" 等标题
            optimized_text = self._remove_transcript_heading(optimized_text)
            enforced = self._enforce_paragraph_max_chars(optimized_text.strip(), max_chars=400)
            return self._ensure_markdown_paragraphs(enforced)
        except Exception as e:
            logger.error(f"单块文本优化失败: {e}")
            return self._apply_basic_formatting(chunk_text)

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

    def _format_long_transcript_in_chunks(self, raw_transcript: str, transcript_language: str, max_chars_per_chunk: int) -> str:
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
                oc = self._format_single_chunk(chunk_with_context, transcript_language)
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
            if s.startswith('**检测语言:**') or s.startswith('**语言概率:**'):
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
            if re.match(r"^#{1,6}\s*transcript(\s+text)?\s*$", stripped, flags=re.I):
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

            step1_system = f"""你是一个精通内容提炼的编辑专家。你的任务是**阅读以下内容，然后为该内容专门设计一套最佳的摘要生成指令（Prompt）**。

你需要判断内容的类型、风格、节奏、信息密度和关键维度，然后写出一个能让后续LLM精准执行摘要的定制化Prompt。

要点：
- 判断内容类型（技术教程/访谈对话/新闻评论/学术讲座/产品发布/故事叙事等）
- 思考这类内容最需要提取什么信息（核心论点？关键数据？操作步骤？观点碰撞？）
- 设计摘要结构（bullet points？分段叙述？表格对比？）
- 指定摘要的目标读者、语气、深度
- 输出语言：{language_name}

**输出格式**：直接输出一段完整的摘要Prompt，用第一人称对"摘要执行者"说话。不要加"以下是定制Prompt："等前缀。"""

            step1_user = f"""请阅读以下内容，然后为该内容设计一个量身定制的摘要生成Prompt：

---
{preview}
---

请输出定制化的摘要Prompt（用{language_name}）："""

            resp1 = self.client.chat.completions.create(
                model=self.advanced_model,
                messages=[
                    {"role": "system", "content": step1_system},
                    {"role": "user", "content": step1_user},
                ],
                max_tokens=2000,
                temperature=0.3,
            )
            custom_prompt = strip_llm_artifacts(resp1.choices[0].message.content or "")
            logger.info(f"双步摘要 Step 1 完成，Prompt长度: {len(custom_prompt)}")

            # ── 第二步：基于定制化Prompt生成最终摘要 ──────────────────────
            logger.info(f"双步摘要 Step 2: 基于定制Prompt生成摘要")

            # 摘要阶段使用完整输入。大上下文模型可以直接阅读长访谈；
            # streaming 只影响返回方式，不影响这里的上下文容量。
            transcript_for_summary = transcript

            step2_system = f"""{custom_prompt}

硬性规则：
- 输出语言：{language_name}
- 不要复述完整原文，不要写长篇逐句重写
- 不要加前言（"Here is..."）、不要加尾注（客套话、"如需调整请告诉我"等）
- Markdown格式：段落间空行分隔；可选用小标题"""

            step2_user = f"""请根据系统提示词，直接总结以下原文内容：

{transcript_for_summary}"""

            resp2 = self.client.chat.completions.create(
                model=self.advanced_model,
                messages=[
                    {"role": "system", "content": step2_system},
                    {"role": "user", "content": step2_user},
                ],
                max_tokens=2200,
                temperature=0.25,
            )
            summary = strip_llm_artifacts(resp2.choices[0].message.content or "")
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
            logger.error(f"双步摘要失败: {e}，回退到单步摘要")
            fallback = self.summarize(transcript, target_language, video_title)
            return {"summary": fallback, "prompt": "(双步摘要回退，使用默认prompt)"}

    def _summarize_single_text(self, transcript: str, target_language: str, video_title: str = None) -> str:
        """
        对单个文本进行摘要
        """
        # 获取目标语言名称
        language_name = self.language_map.get(target_language, "中文（简体）")
        
        # 构建英文提示词，适用于所有目标语言
        system_prompt = f"""You are an expert editor. Write a concise EXECUTIVE SUMMARY in {language_name} of the following material.

Hard rules:
- Length: about 180–450 words in {language_name} (use the lower end if the source is short). Never reproduce long verbatim quotes or extended sentence-by-sentence rewrites of the transcript.
- Content: main thesis, 3–7 key takeaways, important conclusions, and critical facts or numbers only. Tight prose; short bullet lists are OK for takeaways.
- Do NOT restate the full transcript, do NOT add preamble ("Here is…"), and do NOT add closings such as offers to revise or "let me know if…" / 客套尾注.
- Markdown: optional `## Key takeaways` then paragraphs; avoid decorative filler headings.

Output ONLY the summary body in {language_name}."""

        user_prompt = f"""Summarize the following content in {language_name}. Follow the system rules strictly (brief executive summary, no meta-commentary):

{transcript}"""

        logger.info(f"正在生成{language_name}摘要...")
        
        # 调用OpenAI API
        response = self.client.chat.completions.create(
            model=self.advanced_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            max_tokens=2200,
            temperature=0.25
        )
        
        summary = strip_llm_artifacts(response.choices[0].message.content or "")

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
            
            system_prompt = f"""You are a summarization expert. Write a brief section summary in {language_name}.

This is part {i+1} of {len(chunks)} of the full transcript.

Rules:
- About 80–160 words in {language_name}; bullets OK for key points.
- Do not echo the transcript verbatim; capture only new information in this segment.
- No preamble or meta-closings."""

            user_prompt = f"""[Part {i+1}/{len(chunks)}] Summarize in {language_name} (80–160 words, tight prose):

{chunk}

Output content only, no headings like "Summary:"."""

            try:
                response = self.client.chat.completions.create(
                    model=self.advanced_model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    max_tokens=600,
                    temperature=0.25
                )
                
                chunk_summary = strip_llm_artifacts(response.choices[0].message.content or "")
                # 空块摘要视为失败，用截断原文兜底，避免整体摘要塌缩为空
                if not chunk_summary.strip():
                    logger.warning(f"第 {i+1} 块摘要返回空，使用原文片段兜底")
                    chunk_summary = f"第{i+1}部分内容概述：" + chunk[:200] + "..."
                chunk_summaries.append(chunk_summary)

            except Exception as e:
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
            system_prompt = f"""You integrate partial summaries into ONE concise executive summary in {language_name}.

Rules:
- Total length about 280–650 words in {language_name}; remove duplication, do not expand into a transcript-length rewrite.
- Markdown: paragraphs separated by blank lines; optional `## Key takeaways` only if it adds clarity.
- No preamble, no meta-closings (e.g. offers to revise or "let me know")."""

            user_prompt = f"""Merge the following partial summaries into one executive summary in {language_name}:

{combined_summaries}"""

            response = self.client.chat.completions.create(
                model=self.advanced_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                max_tokens=2200,
                temperature=0.25
            )

            integrated = strip_llm_artifacts(response.choices[0].message.content or "")
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
