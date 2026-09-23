import httpx
import pytest

import app.crawler as crawler_module
from app.crawler import Crawler, canonical_url


@pytest.fixture(autouse=True)
def allow_test_hosts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(crawler_module, "validate_public_url", lambda url: url)


@pytest.mark.asyncio
async def test_collects_feed_and_full_article() -> None:
    feed = b"""<?xml version="1.0"?><rss version="2.0"><channel><title>Feed</title>
    <item><title>New release</title><link>https://news.test/post/1?utm_source=rss</link>
    <description>short</description></item></channel></rss>"""
    article = b"<html><head><title>New release</title></head><body><main><p>This is the full article with much more useful content for readers.</p></main></body></html>"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/feed.xml":
            return httpx.Response(200, content=feed, headers={"content-type": "application/rss+xml"})
        return httpx.Response(200, content=article, headers={"content-type": "text/html"})

    crawler = Crawler(httpx.MockTransport(handler))
    result = await crawler.collect({"url": "https://news.test/feed.xml", "kind": "auto"})
    assert len(result) == 1
    assert result[0]["title"] == "New release"
    assert result[0]["url"] == "https://news.test/post/1"
    assert "full article" in result[0]["content"]


@pytest.mark.asyncio
async def test_web_selector_discovers_article() -> None:
    listing = b"""<html><body>
    <div class='item'><a href='/2026/09/story-1'>Important security story one</a></div>
    <div class='item'><a href='/2026/09/story-2'>Important security story two</a></div>
    <div class='item'><a href='/2026/09/story-3'>Important security story three</a></div>
    </body></html>"""
    story = b"<html><head><title>Security story</title></head><body><article><p>Detailed vulnerability analysis and mitigation advice.</p></article></body></html>"

    def handler(request: httpx.Request) -> httpx.Response:
        body = listing if request.url.path == "/news" else story
        return httpx.Response(200, content=body, headers={"content-type": "text/html"})

    crawler = Crawler(httpx.MockTransport(handler))
    result = await crawler.collect(
        {
            "url": "https://news.test/news",
            "kind": "web",
            "item_selector": ".item",
            "max_pages": 2,
        }
    )
    assert len(result) == 2
    assert result[0]["title"] == "Security story"
    assert result[0]["url"].startswith("https://news.test/2026/09/story-")


def test_canonical_url_removes_tracking_only() -> None:
    value = canonical_url("HTTPS://Example.COM/a?utm_medium=x&id=7#part")
    assert value == "https://example.com/a?id=7"
