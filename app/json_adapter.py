from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from app.crawler import canonical_url, make_article

MAX_JSON_ITEMS = 100
ITEM_KEYS = ("items", "results", "data", "advisories", "articles")


def json_articles(body: bytes, base_url: str) -> list[dict]:
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("JSON 信息源返回的内容不是有效 JSON") from exc

    items = _items(payload)
    articles: list[dict] = []
    seen: set[str] = set()
    for item in items[:MAX_JSON_ITEMS]:
        if not isinstance(item, dict):
            continue
        raw_url = _first_text(item, "html_url", "external_url", "url", "link", "id")
        if not raw_url:
            continue
        link = urlparse(urljoin(base_url, raw_url))
        if link.scheme not in {"http", "https"} or not link.hostname or link.username or link.password:
            continue
        url = canonical_url(link.geturl())
        if url in seen:
            continue
        title = _first_text(item, "title", "summary", "name")
        if not title:
            continue
        title = BeautifulSoup(title, "html.parser").get_text(" ", strip=True)
        if not title:
            continue
        content = _first_text(item, "content_text", "description", "body", "content")
        if not content:
            content = BeautifulSoup(
                _first_text(item, "content_html", "summary"), "html.parser"
            ).get_text("\n", strip=True)
        author = item.get("author") or item.get("authors")
        if isinstance(author, list):
            author = author[0] if author else None
        if isinstance(author, dict):
            author = author.get("name") or author.get("login")
        published = _first_text(
            item, "date_published", "published_at", "published", "created_at", "updated_at"
        )
        articles.append(
            make_article(
                title=title,
                url=url,
                content=content,
                author=author if isinstance(author, str) else "",
                published_at=_iso_date(published),
            )
        )
        seen.add(url)
    if items and not articles:
        raise ValueError("JSON 条目缺少可用的标题或 http/https 文章链接")
    return articles


def _items(payload: Any) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ITEM_KEYS:
            value = payload.get(key)
            if isinstance(value, list):
                return value
            if isinstance(value, dict):
                for nested_key in ITEM_KEYS:
                    if isinstance(value.get(nested_key), list):
                        return value[nested_key]
    raise ValueError("JSON 信息源需要条目数组，或包含 items/results/data 等数组的对象")


def _first_text(item: dict, *keys: str) -> str:
    for key in keys:
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _iso_date(value: str) -> str | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).isoformat()
    except ValueError:
        return None
