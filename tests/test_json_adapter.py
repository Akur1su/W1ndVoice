import json
from pathlib import Path

import httpx
import pytest
from bs4 import BeautifulSoup
from fastapi.testclient import TestClient

import app.crawler as crawler_module
from app import main
from app.crawler import Crawler
from app.database import Database
from app.service import NewsService


@pytest.fixture(autouse=True)
def allow_test_hosts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(crawler_module, "validate_public_url", lambda url: url)


def test_json_source_can_be_added_from_ui(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    database = Database(tmp_path / "ui.db")
    monkeypatch.setattr(main, "db", database)
    monkeypatch.setattr(main, "validate_public_url", lambda url: url)
    client = TestClient(main.app)
    page = BeautifulSoup(client.get("/sources").text, "html.parser")
    assert page.select_one('select[name="kind"] option[value="json"]') is not None

    response = client.post(
        "/api/sources",
        json={
            "name": "GitHub Advisories",
            "url": "https://api.github.com/advisories?type=reviewed&per_page=100",
            "kind": "json",
        },
    )
    assert response.status_code == 201
    assert response.json()["kind"] == "json"


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["json", "auto"])
async def test_github_advisories_json_source(tmp_path: Path, kind: str) -> None:
    payload = [
        {
            "ghsa_id": "GHSA-abcd-1234-efgh",
            "url": "https://api.github.com/advisories/GHSA-abcd-1234-efgh",
            "html_url": "https://github.com/advisories/GHSA-abcd-1234-efgh?utm_source=api",
            "summary": "Security fix",
            "description": "Affected versions: < 2.0\nUpgrade to 2.0.",
            "published_at": "2026-09-23T21:54:50Z",
        }
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/advisories"
        return httpx.Response(
            200, json=payload, headers={"content-type": "application/vnd.github+json"}
        )

    db = Database(tmp_path / "json.db")
    source = db.add_source(
        {
            "name": "GitHub Advisories",
            "url": "https://api.github.com/advisories?type=reviewed&per_page=100",
            "category": "漏洞",
            "kind": kind,
            "fetch_interval_hours": 1,
        }
    )
    service = NewsService(db, Crawler(httpx.MockTransport(handler)), object())  # type: ignore[arg-type]
    first = await service.fetch_source(source["id"])
    second = await service.fetch_source(source["id"])

    assert first["found"] == first["changed"] == 1
    assert second["found"] == 1 and second["changed"] == 0
    article = db.list_articles()[0]
    assert article["title"] == "Security fix"
    assert article["url"] == "https://github.com/advisories/GHSA-abcd-1234-efgh"
    assert "< 2.0" in article["content"]
    assert article["published_at"] == "2026-09-23T21:54:50+00:00"


@pytest.mark.asyncio
async def test_json_feed_wrapped_items_and_html_content() -> None:
    body = json.dumps(
        {
            "version": "https://jsonfeed.org/version/1.1",
            "items": [
                {
                    "id": "1",
                    "url": "/posts/1",
                    "title": "New <b>post</b>",
                    "content_html": "<p>Full <em>article</em></p>",
                    "author": {"name": "Alice"},
                    "date_published": "2026-09-24T08:00:00+08:00",
                }
            ],
        }
    ).encode()

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body, headers={"content-type": "application/feed+json"})

    articles = await Crawler(httpx.MockTransport(handler)).collect(
        {"url": "https://feed.test/feed.json", "kind": "auto"}
    )
    assert articles[0]["url"] == "https://feed.test/posts/1"
    assert articles[0]["title"] == "New post"
    assert articles[0]["content"] == "Full\narticle"
    assert articles[0]["author"] == "Alice"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("body", "error"),
    [
        (b"{not json", "有效 JSON"),
        (b'{"message":"API error"}', "条目数组"),
        (b'[{"title":"Missing link"}]', "标题或"),
    ],
)
async def test_invalid_json_source_reports_error(body: bytes, error: str) -> None:
    crawler = Crawler(
        httpx.MockTransport(
            lambda _request: httpx.Response(200, content=body, headers={"content-type": "application/json"})
        )
    )
    with pytest.raises(ValueError, match=error):
        await crawler.collect({"url": "https://api.test/data", "kind": "json"})


@pytest.mark.asyncio
async def test_json_skips_unsafe_links() -> None:
    body = json.dumps(
        [
            {"title": "Unsafe", "url": "javascript:alert(1)"},
            {"title": "Valid", "url": "https://example.com/post"},
        ]
    ).encode()
    crawler = Crawler(httpx.MockTransport(lambda _request: httpx.Response(200, content=body)))
    articles = await crawler.collect({"url": "https://api.test/data", "kind": "json"})
    assert [article["title"] for article in articles] == ["Valid"]
