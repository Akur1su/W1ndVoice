from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from time import struct_time
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

import feedparser
import httpx
import trafilatura
from bs4 import BeautifulSoup

from app.security import validate_public_url

USER_AGENT = "W1ndVoice/0.1 (+local self-hosted news monitor)"
MAX_DOWNLOAD_BYTES = 5 * 1024 * 1024
TRACKING_KEYS = {"fbclid", "gclid", "mc_cid", "mc_eid"}


@dataclass
class Download:
    url: str
    body: bytes
    content_type: str


class Crawler:
    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.transport = transport

    async def download(self, url: str) -> Download:
        current = validate_public_url(url)
        async with httpx.AsyncClient(
            headers={"User-Agent": USER_AGENT, "Accept": "application/json,application/feed+json,application/rss+xml,text/html,*/*"},
            timeout=httpx.Timeout(20, connect=10),
            follow_redirects=False,
            transport=self.transport,
        ) as client:
            for _ in range(5):
                async with client.stream("GET", current) as response:
                    if response.is_redirect:
                        location = response.headers.get("location")
                        if not location:
                            raise ValueError("重定向响应缺少 Location")
                        current = validate_public_url(urljoin(current, location))
                        continue
                    response.raise_for_status()
                    size = int(response.headers.get("content-length", 0) or 0)
                    if size > MAX_DOWNLOAD_BYTES:
                        raise ValueError("页面超过 5 MiB 抓取上限")
                    chunks: list[bytes] = []
                    received = 0
                    async for chunk in response.aiter_bytes():
                        received += len(chunk)
                        if received > MAX_DOWNLOAD_BYTES:
                            raise ValueError("页面超过 5 MiB 抓取上限")
                        chunks.append(chunk)
                    return Download(
                        str(response.url), b"".join(chunks), response.headers.get("content-type", "")
                    )
        raise ValueError("重定向次数过多")

    async def collect(self, source: dict) -> list[dict]:
        first = await self.download(source["url"])
        kind = source.get("kind", "auto")
        content_type = first.content_type.split(";", 1)[0].strip().lower()
        looks_json = content_type == "application/json" or content_type.endswith("+json")
        if not content_type:
            looks_json = first.body.lstrip().startswith((b"{", b"["))
        if kind == "json" or (kind == "auto" and looks_json):
            from app.json_adapter import json_articles

            return json_articles(first.body, first.url)

        parsed = feedparser.parse(first.body)
        if kind == "rss" or (kind == "auto" and parsed.version and parsed.entries):
            return await self._from_feed(parsed, first.url)

        soup = BeautifulSoup(first.body, "html.parser")
        if kind == "auto":
            alternate = soup.select_one(
                'link[rel~="alternate"][type="application/rss+xml"], '
                'link[rel~="alternate"][type="application/atom+xml"]'
            )
            if alternate and alternate.get("href"):
                feed_url = urljoin(first.url, str(alternate["href"]))
                feed_download = await self.download(feed_url)
                discovered = feedparser.parse(feed_download.body)
                if discovered.entries:
                    return await self._from_feed(discovered, feed_download.url)

        urls = self._discover_links(soup, first.url, source.get("item_selector", ""))
        if not urls:
            return [self._article_from_html(first.url, first.body)]

        articles: list[dict] = []
        max_pages = min(max(int(source.get("max_pages", 5)), 1), 100)
        for url in urls[:max_pages]:
            try:
                page = await self.download(url)
                articles.append(self._article_from_html(page.url, page.body))
            except (httpx.HTTPError, ValueError):
                continue
        return articles or [self._article_from_html(first.url, first.body)]

    async def _from_feed(self, feed: feedparser.FeedParserDict, base_url: str) -> list[dict]:
        articles: list[dict] = []
        for entry in feed.entries[:20]:
            link = canonical_url(urljoin(base_url, entry.get("link", "")))
            if not link:
                continue
            content = self._feed_content(entry)
            try:
                page = await self.download(link)
                extracted = self._extract_text(page.body)
                if len(extracted) > len(content):
                    content = extracted
                link = canonical_url(page.url)
            except (httpx.HTTPError, ValueError):
                pass
            title = BeautifulSoup(entry.get("title", "无标题"), "html.parser").get_text(
                " ", strip=True
            )
            articles.append(
                make_article(
                    title=title or "无标题",
                    url=link,
                    content=content,
                    author=entry.get("author", ""),
                    published_at=parse_feed_date(
                        entry.get("published_parsed") or entry.get("updated_parsed")
                    ),
                )
            )
        return articles

    @staticmethod
    def _feed_content(entry: feedparser.FeedParserDict) -> str:
        raw = ""
        if entry.get("content"):
            raw = entry.content[0].get("value", "")
        raw = raw or entry.get("summary", "")
        return BeautifulSoup(raw, "html.parser").get_text("\n", strip=True)

    @staticmethod
    def _extract_text(body: bytes) -> str:
        extracted = trafilatura.extract(
            body, include_comments=False, include_tables=True, favor_precision=True
        )
        if extracted:
            return extracted.strip()
        soup = BeautifulSoup(body, "html.parser")
        for node in soup.select("script, style, nav, footer, header, aside"):
            node.decompose()
        return "\n".join(p.get_text(" ", strip=True) for p in soup.select("p") if p.get_text(strip=True))

    def _article_from_html(self, url: str, body: bytes) -> dict:
        soup = BeautifulSoup(body, "html.parser")
        title_node = soup.select_one('meta[property="og:title"]')
        title = ""
        if title_node:
            title = str(title_node.get("content", ""))
        if not title and soup.title:
            title = soup.title.get_text(" ", strip=True)
        return make_article(title or url, canonical_url(url), self._extract_text(body))

    @staticmethod
    def _discover_links(soup: BeautifulSoup, base_url: str, selector: str) -> list[str]:
        containers = soup.select(selector) if selector else [soup]
        base_host = urlparse(base_url).hostname
        scored: list[tuple[int, str]] = []
        seen: set[str] = set()
        for container in containers:
            anchors = [container] if getattr(container, "name", None) == "a" else container.select("a[href]")
            for anchor in anchors:
                href = anchor.get("href")
                if not href:
                    continue
                url = canonical_url(urljoin(base_url, str(href)))
                parsed = urlparse(url)
                if parsed.scheme not in {"http", "https"} or parsed.hostname != base_host or url in seen:
                    continue
                text = anchor.get_text(" ", strip=True)
                path = parsed.path.lower()
                if len(text) < 8 or path in {"", "/"}:
                    continue
                score = min(len(text), 80)
                if re.search(r"/20\d{2}[/_-]\d{1,2}|/\d{4}/\d{1,2}/|\d{4}-\d{2}-\d{2}", path):
                    score += 80
                if any(token in path for token in ("article", "news", "blog", "post", "security", "cve")):
                    score += 30
                if selector:
                    score += 100
                seen.add(url)
                scored.append((score, url))
        scored.sort(reverse=True)
        return [url for _, url in scored]


def canonical_url(url: str) -> str:
    if not url:
        return ""
    parsed = urlparse(url)
    query = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.lower().startswith("utm_") and key.lower() not in TRACKING_KEYS
    ]
    path = parsed.path or "/"
    return urlunparse(
        (parsed.scheme.lower(), parsed.netloc.lower(), path, "", urlencode(query), "")
    )


def parse_feed_date(value: struct_time | None) -> str | None:
    if not value:
        return None
    return datetime(*value[:6], tzinfo=UTC).isoformat()


def make_article(
    title: str, url: str, content: str, author: str = "", published_at: str | None = None
) -> dict:
    clean_content = content.strip()[:100_000]
    digest = hashlib.sha256(f"{title}\n{clean_content}".encode()).hexdigest()
    return {
        "title": title.strip()[:500],
        "url": canonical_url(url),
        "content": clean_content,
        "author": author.strip()[:200],
        "published_at": published_at,
        "content_hash": digest,
    }
