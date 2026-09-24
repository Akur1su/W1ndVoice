from pathlib import Path

from bs4 import BeautifulSoup
from fastapi.testclient import TestClient

from app import main
from app.crawler import make_article
from app.database import Database


def test_analysis_response_matches_article_card_fields(tmp_path: Path, monkeypatch) -> None:
    database = Database(tmp_path / "analysis-card.db")
    monkeypatch.setattr(main, "db", database)
    monkeypatch.setattr(main.analyzer, "db", database)
    source = database.add_source(
        {"name": "测试源", "url": "https://example.com/feed", "category": "技术",
         "kind": "rss", "fetch_interval_hours": 1}
    )
    article_id = database.save_articles(
        source["id"], [make_article("测试文章", "https://example.com/story", "原文")]
    )[0]
    analysis = {
        "summary": "新的中文摘要", "importance": 87,
        "tags": ["AI", "安全"], "risk_level": "high",
    }

    async def fake_analyze(_article_id: int):
        database.save_analysis(_article_id, analysis)
        return analysis

    monkeypatch.setattr(main.analyzer, "analyze", fake_analyze)
    client = TestClient(main.app)
    assert client.post(f"/api/articles/{article_id}/analyze").json() == analysis
    saved = client.get(f"/api/articles/{article_id}/analysis").json()
    assert saved["ai_status"] == "done"
    assert saved["summary"] == analysis["summary"]
    page = BeautifulSoup(client.get("/stream").text, "html.parser")
    card = page.select_one(".intel-article")
    assert card.select_one(".summary").get_text(strip=True) == analysis["summary"]
    assert card.select_one(".article-importance").get_text(strip=True) == "重要度 87"
    assert card.select_one(".card-meta .risk.high")
    assert [tag.get_text(strip=True) for tag in card.select(".tags span")] == ["#AI", "#安全"]
    assert card.select_one(".view-analysis")
