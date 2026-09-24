from pathlib import Path

from bs4 import BeautifulSoup
from fastapi.testclient import TestClient

from app import main
from app.crawler import make_article
from app.database import Database


def test_stream_limit_is_saved_and_applied_per_source(tmp_path: Path, monkeypatch) -> None:
    database = Database(tmp_path / "stream-settings.db")
    monkeypatch.setattr(main, "db", database)
    monkeypatch.setattr(main.analyzer, "db", database)
    client = TestClient(main.app)
    sources = [
        database.add_source(
            {"name": f"源 {index}", "url": f"https://example.com/feed-{index}",
             "category": "技术", "kind": "rss", "fetch_interval_hours": 1}
        )
        for index in range(2)
    ]
    for source in sources:
        database.save_articles(
            source["id"],
            [make_article(f"文章 {source['id']}-{index}",
                          f"https://example.com/article-{source['id']}-{index}", "正文")
             for index in range(3)],
        )

    assert client.get("/api/settings/stream").json() == {"per_source_limit": 100}
    assert client.put("/api/settings/stream", json={"per_source_limit": 2}).json() == {
        "per_source_limit": 2
    }
    assert database.get_settings()["stream_articles_per_source"] == "2"
    settings_page = BeautifulSoup(client.get("/settings").text, "html.parser")
    assert settings_page.select_one('#stream-settings-form input[name="per_source_limit"]')[
        "value"
    ] == "2"
    stream = BeautifulSoup(client.get("/stream").text, "html.parser")
    assert [len(group.select(".intel-article")) for group in stream.select(".intel-source")] == [
        2, 2
    ]
    assert database.stats()["articles"] == 6
    assert client.put("/api/settings/stream", json={"per_source_limit": 0}).status_code == 422
    assert client.put("/api/settings/stream", json={"per_source_limit": 501}).status_code == 422
