from pathlib import Path

import httpx
from bs4 import BeautifulSoup
from fastapi.testclient import TestClient

from app import main
from app.crawler import make_article
from app.database import Database


def test_navigation_uses_real_pages_and_shows_only_selected_view(tmp_path: Path, monkeypatch) -> None:
    database = Database(tmp_path / "navigation.db")
    monkeypatch.setattr(main, "db", database)
    monkeypatch.setattr(main.analyzer, "db", database)
    client = TestClient(main.app)

    expected = {
        "/": "home",
        "/sources": "sources",
        "/settings": "settings",
        "/stream": "stream",
    }
    for path, selected in expected.items():
        response = client.get(path)
        assert response.status_code == 200
        page = BeautifulSoup(response.text, "html.parser")
        assert page.select_one('.brand[aria-label="W1ndVoice 首页"]')["href"] == "/"
        assert page.select_one(".nav-stream") is None
        assert page.select_one(".home-stream-card")["href"] == "/stream"
        assert {link["href"] for link in page.select(".header-actions .nav-action")} == {
            "/sources", "/settings"
        }
        for view, section in ((node["data-view"], node) for node in page.select(".page-view")):
            assert section.has_attr("hidden") is (view != selected)
        if selected != "home":
            assert page.select_one(f'[data-view="{selected}"] .back-home')["href"] == "/"
    assert client.get("/settings/ai", follow_redirects=False).headers["location"] == "/settings#ai-settings"
    assert client.get("/settings/server", follow_redirects=False).headers["location"] == "/settings#server-settings"


def test_stream_deletes_articles_and_whole_sources(tmp_path: Path, monkeypatch) -> None:
    database = Database(tmp_path / "stream.db")
    monkeypatch.setattr(main, "db", database)
    monkeypatch.setattr(main.analyzer, "db", database)
    client = TestClient(main.app)
    first = database.add_source(
        {
            "name": "第一源", "url": "https://first.example/feed", "category": "漏洞",
            "kind": "rss", "fetch_interval_hours": 1,
        }
    )
    second = database.add_source(
        {
            "name": "第二源", "url": "https://second.example/feed", "category": " 漏洞 ",
            "kind": "rss", "fetch_interval_hours": 1,
        }
    )
    third = database.add_source(
        {
            "name": "第三源", "url": "https://third.example/feed", "category": "AI",
            "kind": "rss", "fetch_interval_hours": 1,
        }
    )
    first_article = database.save_articles(
        first["id"], [make_article("第一篇", "https://first.example/one", "正文")]
    )[0]
    second_article = database.save_articles(
        first["id"], [make_article("第二篇", "https://first.example/two", "正文")]
    )[0]
    other_source_article = database.save_articles(
        second["id"], [make_article("另一源文章", "https://second.example/story", "正文")]
    )[0]

    page = BeautifulSoup(client.get("/stream").text, "html.parser")
    groups = page.select(".intel-group")
    assert {group["data-category"] for group in groups} == {"漏洞", "AI"}
    vulnerability = page.select_one('.intel-group[data-category="漏洞"]')
    assert {node["data-source-id"] for node in vulnerability.select(".intel-source")} == {
        str(first["id"]), str(second["id"])
    }
    assert vulnerability.select_one(".intel-group-summary .delete-category")["data-count"] == "2"
    first_group = vulnerability.select_one(f'.intel-source[data-source-id="{first["id"]}"]')
    assert first_group.select_one(".source-name").get_text(strip=True) == "第一源"
    assert first_group.select_one(".intel-source-summary .delete-source")["data-id"] == str(
        first["id"]
    )
    assert {
        button["data-id"]
        for button in first_group.select(".intel-article-summary .delete-article")
    } == {str(first_article), str(second_article)}
    assert page.select_one(f'.intel-source[data-source-id="{second["id"]}"] .delete-article')
    sources_page = BeautifulSoup(client.get("/sources").text, "html.parser")
    assert {option["value"] for option in sources_page.select("#existing-categories option")} == {
        "漏洞", "AI"
    }
    assert len(sources_page.select(".source-category")) == 2

    assert client.delete(f"/api/articles/{first_article}").status_code == 200
    assert database.get_article(second_article)["title"] == "第二篇"
    assert client.delete(f"/api/sources/{first['id']}").status_code == 200
    assert [article["id"] for article in database.list_articles()] == [other_source_article]
    assert {source["id"] for source in database.list_sources()} == {second["id"], third["id"]}
    deleted_category = client.delete("/api/categories", params={"name": "漏洞"})
    assert deleted_category.status_code == 200
    assert deleted_category.json()["sources_deleted"] == 1
    assert {source["id"] for source in database.list_sources()} == {third["id"]}
    assert database.list_articles() == []
    assert client.delete("/api/categories", params={"name": "漏洞"}).status_code == 404


def test_duplicate_source_name_is_rejected_on_create_and_edit(tmp_path: Path, monkeypatch) -> None:
    database = Database(tmp_path / "names.db")
    monkeypatch.setattr(main, "db", database)
    monkeypatch.setattr(main, "validate_public_url", lambda url: url)
    client = TestClient(main.app)
    first = {"name": "Portswigger", "url": "https://first.example/feed", "category": "漏洞"}
    second = {"name": "Other", "url": "https://second.example/feed", "category": "漏洞"}
    assert client.post("/api/sources", json=first).status_code == 201
    created = client.post("/api/sources", json=second)
    assert created.status_code == 201
    duplicate = client.post("/api/sources", json={**second, "name": " portswigger ", "url": "https://third.example/feed"})
    assert duplicate.status_code == 400
    assert "名称已存在" in duplicate.json()["detail"]
    renamed = client.put(f"/api/sources/{created.json()['id']}", json={**second, "name": "PORTSWIGGER"})
    assert renamed.status_code == 400
    assert database.get_source(created.json()["id"])["name"] == "Other"


def test_stream_keeps_older_sources_visible_when_one_source_has_over_100_articles(
    tmp_path: Path, monkeypatch
) -> None:
    database = Database(tmp_path / "many-articles.db")
    monkeypatch.setattr(main, "db", database)
    monkeypatch.setattr(main.analyzer, "db", database)
    newer = database.add_source(
        {"name": "新源", "url": "https://new.example/feed", "category": "漏洞",
         "kind": "json", "fetch_interval_hours": 1}
    )
    older = database.add_source(
        {"name": "旧源", "url": "https://old.example/feed", "category": "技术",
         "kind": "rss", "fetch_interval_hours": 1}
    )
    database.save_articles(
        newer["id"],
        [make_article(f"新文章 {index}", f"https://new.example/{index}", "正文", published_at="2026-09-01T00:00:00+00:00")
         for index in range(101)],
    )
    database.save_articles(
        older["id"],
        [make_article("旧文章", "https://old.example/story", "正文", published_at="2025-01-01T00:00:00+00:00")],
    )

    assert {article["source_id"] for article in database.list_articles(limit=100)} == {newer["id"]}
    stream_articles = database.list_stream_articles(per_source_limit=100)
    assert len(stream_articles) == 101
    assert sum(article["source_id"] == newer["id"] for article in stream_articles) == 100
    page = BeautifulSoup(TestClient(main.app).get("/stream").text, "html.parser")
    older_group = page.select_one(f'.intel-source[data-source-id="{older["id"]}"]')
    assert older_group.select_one(".article-title-text").get_text(strip=True) == "旧文章"


def test_duplicate_source_and_fetch_failure_explain_saved_state(tmp_path: Path, monkeypatch) -> None:
    database = Database(tmp_path / "failed-create.db")
    monkeypatch.setattr(main, "db", database)
    monkeypatch.setattr(main, "validate_public_url", lambda url: url)

    async def fail_fetch(_source_id: int):
        raise httpx.ConnectError("")

    monkeypatch.setattr(main.service, "fetch_source", fail_fetch)
    client = TestClient(main.app)
    payload = {
        "name": "Portswigger", "url": "https://api.github.com/advisories",
        "kind": "json",
    }
    created = client.post("/api/sources", json=payload)
    assert created.status_code == 201
    failed = client.post(f"/api/sources/{created.json()['id']}/fetch")
    assert failed.status_code == 502
    assert "网络或代理" in failed.json()["detail"]
    assert database.get_source(created.json()["id"])["url"] == payload["url"]
    duplicate = client.post("/api/sources", json={**payload, "name": "另一名称"})
    assert duplicate.status_code == 400
    assert "信息源列表" in duplicate.json()["detail"]
