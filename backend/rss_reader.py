"""
RSS/Atom feed reader for ai-transcribe.
Parses feeds, tracks subscriptions, deduplicates entries by link/guid,
supports incremental refresh, and marks entries as processed.
Uses JSON for persistence — no external dependencies.
"""
from __future__ import annotations

import json
import hashlib
import logging
import re
import uuid
import asyncio
import urllib.request
import urllib.error
from urllib.parse import urlparse
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Optional

import xml.etree.ElementTree as ET

logger = logging.getLogger(__name__)


async def fetch_article_text(url: str) -> str:
    """抓取文章网页并提取正文。

    用于「只有标题+链接、正文为空」的 feed（如 surma.dev）：feed 条目本身
    没有 content/summary，需回到 link 指向的页面提取正文。
    依赖 trafilatura 做主体内容提取；失败或无正文时返回空字符串。
    """
    if not url:
        return ""
    try:
        import trafilatura
    except ImportError:
        logger.warning("未安装 trafilatura，无法从链接提取正文")
        return ""

    def _extract() -> str:
        req = urllib.request.Request(
            url, headers={"User-Agent": "ai-transcribe/1.0 (Article Reader)"}
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            if resp.status != 200:
                raise ValueError(f"HTTP {resp.status}")
            html = resp.read().decode("utf-8", errors="replace")
        return trafilatura.extract(html, url=url) or ""

    try:
        return (await asyncio.to_thread(_extract)).strip()
    except Exception as e:
        logger.warning(f"提取文章正文失败 {url}: {e}")
        return ""


def _stable_id(*parts: str) -> str:
    """生成稳定的短 ID（基于内容的 SHA1 前 12 位）。"""
    raw = "|".join(p for p in parts if p)
    return hashlib.sha1(raw.encode()).hexdigest()[:12]


class RSSReader:
    """RSS/Atom 订阅管理器 — JSON 持久化，支持增量刷新"""

    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.feeds_file = data_dir / "rss_feeds.json"
        self._feeds: dict = {}
        self._load()

    # ── 持久化 ────────────────────────────────────────────────
    def _load(self):
        try:
            if self.feeds_file.exists():
                self._feeds = json.loads(self.feeds_file.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning(f"加载RSS订阅数据失败: {e}")
            self._feeds = {}

    def _save(self):
        try:
            self.feeds_file.parent.mkdir(parents=True, exist_ok=True)
            self.feeds_file.write_text(
                json.dumps(self._feeds, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            logger.error(f"保存RSS订阅数据失败: {e}")

    # ── HTTP 抓取 ─────────────────────────────────────────────
    def _fetch_url(self, url: str) -> str:
        """同步抓取 URL（通过 asyncio.to_thread 调用）。"""
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "ai-transcribe/1.0 (RSS Reader)",
                "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml",
            },
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            if resp.status != 200:
                raise ValueError(f"HTTP {resp.status}")
            return resp.read().decode("utf-8", errors="replace")

    async def fetch_feed(self, feed_url: str) -> dict:
        """抓取并解析 RSS/Atom，但不写入服务器持久化。"""
        feed_url = feed_url.strip()
        parsed = urlparse(feed_url)
        if not parsed.scheme or not parsed.netloc:
            raise ValueError("无效的URL")

        content = await asyncio.to_thread(self._fetch_url, feed_url)
        feed_type, title, entries = await asyncio.to_thread(
            self._parse_feed, content
        )

        now = datetime.now(timezone.utc).isoformat()
        return {
            "id": _stable_id(feed_url),
            "url": feed_url,
            "title": title or parsed.netloc,
            "type": feed_type,
            "added_at": now,
            "last_checked": now,
            "last_error": None,
            "entries": entries,
        }

    # ── 添加订阅 ──────────────────────────────────────────────
    async def add_feed(self, feed_url: str) -> dict:
        """首次添加 RSS/Atom 订阅，抓取后存入。"""
        feed = await self.fetch_feed(feed_url)
        self._feeds[feed["id"]] = feed
        self._save()
        logger.info(f"RSS订阅已添加: {feed['title']} ({feed['url']})")
        return feed

    # ── 刷新订阅（增量更新）───────────────────────────────────
    async def refresh_feed(self, feed_id: str) -> dict:
        """重新抓取 feed，只添加新条目（按 link/guid 去重），保留已处理状态。"""
        if feed_id not in self._feeds:
            raise ValueError("订阅不存在")

        feed = self._feeds[feed_id]
        feed_url = feed["url"]
        now = datetime.now(timezone.utc).isoformat()

        # 保存旧条目的「已处理」状态（按 entry.id 索引）
        old_status: dict[str, str] = {}
        for e in feed.get("entries", []):
            if e.get("processed"):
                old_status[e["id"]] = e["processed"]

        try:
            content = await asyncio.to_thread(self._fetch_url, feed_url)
            feed_type, title, new_entries = await asyncio.to_thread(
                self._parse_feed, content
            )

            # 构建旧条目 ID 集合，用于去重
            existing_ids = {e["id"] for e in feed.get("entries", [])}
            added_count = 0

            for entry in new_entries:
                if entry["id"] not in existing_ids:
                    # 恢复已处理状态（跨刷新生效的概率很低，但保留逻辑）
                    if entry["id"] in old_status:
                        entry["processed"] = old_status[entry["id"]]
                    feed["entries"].insert(0, entry)
                    existing_ids.add(entry["id"])
                    added_count += 1

            # 更新时间戳和标题（标题可能变化）
            feed["last_checked"] = now
            feed["last_error"] = None
            if title:
                feed["title"] = title
            if feed_type:
                feed["type"] = feed_type

            self._save()
            logger.info(
                f"RSS刷新完成: {feed['title']}, 新增 {added_count} 条"
            )
            return {
                "feed": feed,
                "new_count": added_count,
                "total_count": len(feed["entries"]),
            }

        except Exception as e:
            feed["last_error"] = str(e)[:200]
            feed["last_checked"] = now
            self._save()
            logger.warning(f"RSS刷新失败 {feed['title']}: {e}")
            raise

    # ── 标记条目已处理 ────────────────────────────────────────
    def mark_entry_processed(
        self, feed_id: str, entry_id: str, action: str
    ):
        """action: 'summarized' | 'downloaded'"""
        if feed_id not in self._feeds:
            return
        for entry in self._feeds[feed_id].get("entries", []):
            if entry["id"] == entry_id:
                entry["processed"] = action
                self._save()
                return

    # ── 查询 ──────────────────────────────────────────────────
    def list_feeds(self) -> list:
        result = []
        for fid, feed in self._feeds.items():
            entry_count = len(feed.get("entries", []))
            new_count = sum(
                1 for e in feed.get("entries", [])
                if not e.get("processed")
            )
            result.append({
                "id": fid,
                "title": feed["title"],
                "type": feed["type"],
                "url": feed["url"],
                "last_checked": feed.get("last_checked", ""),
                "last_error": feed.get("last_error"),
                "entry_count": entry_count,
                "new_count": new_count,
            })
        return result

    async def get_entries(self, feed_id: str) -> list:
        if feed_id not in self._feeds:
            raise ValueError("订阅不存在")
        return self._feeds[feed_id].get("entries", [])

    def get_entry_by_id(
        self, feed_id: str, entry_id: str
    ) -> Optional[dict]:
        if feed_id not in self._feeds:
            return None
        for entry in self._feeds[feed_id].get("entries", []):
            if entry["id"] == entry_id:
                return entry
        return None

    def remove_feed(self, feed_id: str):
        if feed_id in self._feeds:
            del self._feeds[feed_id]
            self._save()
            logger.info(f"RSS订阅已删除: {feed_id}")

    # ── Feed 解析 ─────────────────────────────────────────────
    def _parse_feed(self, content: str) -> tuple[str, str, list]:
        try:
            root = ET.fromstring(content)
            ns_atom = "http://www.w3.org/2005/Atom"
            if root.tag == f"{{{ns_atom}}}feed" or root.tag == "feed":
                return self._parse_atom(root, ns_atom)
            channel = root.find("channel")
            if channel is not None:
                return self._parse_rss(channel)
            raise ValueError("无法识别的feed格式")
        except ET.ParseError as e:
            raise ValueError(f"XML解析失败: {e}")

    def _parse_rss(self, channel) -> tuple[str, str, list]:
        ns_content = "http://purl.org/rss/1.0/modules/content/"
        title = self._text(channel, "title") or "未命名播客"
        items = channel.findall("item")
        entries = []
        for item in items:
            entry_title = self._text(item, "title") or "无标题"
            link = self._text(item, "link") or ""
            guid = self._text(item, "guid") or ""
            description = self._text(item, "description") or ""
            content = self._text(item, f"{{{ns_content}}}encoded") or description
            pub_date = self._text(item, "pubDate") or ""

            enclosure_url = ""
            enclosure_type = ""
            enclosure = item.find("enclosure")
            if enclosure is not None:
                enc_type = (enclosure.get("type", "") or "").strip().lower()
                # 只保留音频/视频类型的 enclosure；图片（博客封面）跳过
                if self._is_media_enclosure(enc_type):
                    enclosure_url = enclosure.get("url", "")
                    enclosure_type = enc_type

            # 稳定 ID：优先 guid，其次 link，再次 title+enclosure
            eid = _stable_id(guid or link or (entry_title + enclosure_url))

            entries.append({
                "id": eid,
                "title": entry_title,
                "link": link,
                "guid": guid,
                "summary": self._strip_html(description),
                "content": self._strip_html(content),
                "published": pub_date,
                "enclosure_url": enclosure_url,
                "enclosure_type": enclosure_type,
                "processed": None,  # null | "summarized" | "downloaded"
            })
        entries.sort(key=self._published_sort_key, reverse=True)
        return ("rss", title, entries)

    def _parse_atom(self, root, ns) -> tuple[str, str, list]:
        title = self._text(root, f"{{{ns}}}title") or "未命名博客"
        entry_nodes = root.findall(f"{{{ns}}}entry")
        entries = []
        for entry in entry_nodes:
            entry_title = self._text(entry, f"{{{ns}}}title") or "无标题"

            # 找 link[rel=alternate]
            link = ""
            for le in entry.findall(f"{{{ns}}}link"):
                rel = le.get("rel", "alternate")
                if rel == "alternate" or not rel:
                    link = le.get("href", "")
                    break
            if not link and entry.findall(f"{{{ns}}}link"):
                link = entry.findall(f"{{{ns}}}link")[0].get("href", "")

            entry_id = self._text(entry, f"{{{ns}}}id") or ""
            summary = self._text(entry, f"{{{ns}}}summary") or ""
            content = ""
            content_el = entry.find(f"{{{ns}}}content")
            if content_el is not None:
                content = content_el.text or ""
            if not content:
                content = summary
            published = self._text(entry, f"{{{ns}}}published") or ""
            updated = self._text(entry, f"{{{ns}}}updated") or ""

            enclosure_url = ""
            enclosure_type = ""
            for le in entry.findall(f"{{{ns}}}link"):
                if le.get("rel", "") == "enclosure":
                    enc_type = (le.get("type", "") or "").strip().lower()
                    if self._is_media_enclosure(enc_type):
                        enclosure_url = le.get("href", "")
                        enclosure_type = enc_type
                    break

            eid = _stable_id(entry_id or link or (entry_title + enclosure_url))

            entries.append({
                "id": eid,
                "title": entry_title,
                "link": link,
                "guid": entry_id,
                "summary": self._strip_html(summary),
                "content": self._strip_html(content),
                "published": published or updated,
                "enclosure_url": enclosure_url,
                "enclosure_type": enclosure_type,
                "processed": None,
            })
        entries.sort(key=self._published_sort_key, reverse=True)
        return ("atom", title, entries)

    # ── 工具函数 ──────────────────────────────────────────────
    @staticmethod
    def _published_sort_key(entry: dict) -> datetime:
        raw = (entry.get("published") or "").strip()
        if not raw:
            return datetime.min.replace(tzinfo=timezone.utc)
        try:
            dt = parsedate_to_datetime(raw)
        except (TypeError, ValueError):
            try:
                dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            except ValueError:
                return datetime.min.replace(tzinfo=timezone.utc)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt

    @staticmethod
    def _is_media_enclosure(enc_type: str) -> bool:
        """判断 enclosure type 是否是音频/视频（而非图片等）。
        图片类型明确跳过；未知/缺失类型视为媒体（兼容不写 type 的播客 feed）。"""
        if not enc_type:
            return True  # 无 type → 保守处理，视为音频
        if enc_type.startswith("image/"):
            return False
        if enc_type.startswith("audio/") or enc_type.startswith("video/"):
            return True
        # 其他未知 MIME → 保守处理
        return True

    @staticmethod
    def _text(element, tag) -> str:
        el = element.find(tag)
        return (el.text or "").strip() if el is not None else ""

    @staticmethod
    def _strip_html(text: str) -> str:
        if not text:
            return ""
        text = re.sub(r"<[^>]+>", "", text)
        text = text.replace("&amp;", "&").replace("&lt;", "<")
        text = text.replace("&gt;", ">").replace("&nbsp;", " ")
        text = text.replace("&#39;", "'").replace("&quot;", '"')
        return re.sub(r"\s+", " ", text).strip()
