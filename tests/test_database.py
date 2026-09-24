import sqlite3
from pathlib import Path

from app.crawler import make_article
from app.database import Database


def test_source_and_article_lifecycle(tmp_path: Path) -> None:
    db = Database(tmp_path / "test.db")
    source = db.add_source(
        {
            "name": "Example",
            "url": "https://example.com/feed",
            "category": "技术",
            "kind": "rss",
            "item_selector": "",
            "fetch_interval_hours": 1,
            "auto_analyze": False,
            "enabled": True,
        }
    )

    article = make_article("First", "https://example.com/a?utm_source=test", "body")
    changed = db.save_articles(source["id"], [article])
    assert len(changed) == 1
    assert db.save_articles(source["id"], [article]) == []

    rows = db.list_articles()
    assert rows[0]["url"] == "https://example.com/a"
    assert rows[0]["source_name"] == "Example"
    assert db.stats() == {"sources": 1, "articles": 1, "analyzed": 0}

    db.save_analysis(
        changed[0],
        {"summary": "摘要", "importance": 82, "tags": ["Python"], "risk_level": "none"},
    )
    assert db.get_article(changed[0])["tags"] == ["Python"]
    assert db.stats()["analyzed"] == 1

    updated = db.update_source(
        source["id"],
        {
            "name": "Updated",
            "url": "https://example.com/updated-feed",
            "category": "漏洞",
            "kind": "auto",
            "item_selector": ".entry",
            "fetch_interval_hours": 6,
            "max_pages": 12,
            "auto_fetch_enabled": False,
            "auto_analyze": True,
            "ai_prompt": "只评估漏洞利用风险",
            "enabled": True,
        },
    )
    assert updated["url"] == "https://example.com/updated-feed"
    assert updated["fetch_interval_hours"] == 6
    assert updated["max_pages"] == 12
    assert updated["auto_fetch_enabled"] == 0
    assert updated["ai_prompt"] == "只评估漏洞利用风险"
    assert updated["last_status"] == "配置已更新，等待抓取"

    assert db.delete_article(changed[0]) is True
    assert db.delete_article(changed[0]) is False
    assert db.stats() == {"sources": 1, "articles": 0, "analyzed": 0}


def test_article_content_change_resets_analysis(tmp_path: Path) -> None:
    db = Database(tmp_path / "test.db")
    source = db.add_source(
        {
            "name": "Example",
            "url": "https://example.com",
            "category": "AI",
            "kind": "web",
            "fetch_interval_hours": 1,
        }
    )
    first_id = db.save_articles(
        source["id"], [make_article("Story", "https://example.com/story", "version one")]
    )[0]
    db.save_analysis(
        first_id,
        {"summary": "old", "importance": 10, "tags": [], "risk_level": "none"},
    )
    changed = db.save_articles(
        source["id"], [make_article("Story", "https://example.com/story", "version two")]
    )
    refreshed = db.get_article(first_id)
    assert changed == [first_id]
    assert refreshed["ai_status"] == "idle"
    assert refreshed["summary"] == ""


def test_delete_category_removes_every_source_and_its_articles(tmp_path: Path) -> None:
    db = Database(tmp_path / "categories.db")
    for index, category in enumerate(("漏洞", " 漏洞 ", "AI"), start=1):
        source = db.add_source(
            {
                "name": f"源 {index}", "url": f"https://example.com/feed-{index}",
                "category": category, "kind": "rss", "fetch_interval_hours": 1,
            }
        )
        db.save_articles(
            source["id"],
            [make_article(f"文章 {index}", f"https://example.com/article-{index}", "正文")],
        )
    assert db.delete_category("漏洞") == 2
    assert [source["name"] for source in db.list_sources()] == ["源 3"]
    assert [article["title"] for article in db.list_articles()] == ["文章 3"]


def test_existing_duplicate_names_can_still_be_edited_without_renaming(tmp_path: Path) -> None:
    db = Database(tmp_path / "legacy-names.db")
    source = db.add_source(
        {
            "name": "旧名称", "url": "https://example.com/first", "category": "技术",
            "kind": "rss", "fetch_interval_hours": 1,
        }
    )
    with db.connect() as connection:
        connection.execute(
            "INSERT INTO sources (name, url, category, created_at) VALUES (?, ?, ?, ?)",
            ("旧名称", "https://example.com/second", "技术", "2026-01-01T00:00:00+00:00"),
        )
    edited = db.update_source(
        source["id"],
        {"name": "旧名称", "url": source["url"], "category": "漏洞",
         "kind": "rss", "fetch_interval_hours": 1},
    )
    assert edited["category"] == "漏洞"


def test_migrates_minute_interval_to_hours(tmp_path: Path) -> None:
    path = tmp_path / "legacy.db"
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE sources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            url TEXT NOT NULL UNIQUE,
            category TEXT NOT NULL DEFAULT '技术',
            kind TEXT NOT NULL DEFAULT 'auto',
            item_selector TEXT NOT NULL DEFAULT '',
            fetch_interval_minutes INTEGER NOT NULL DEFAULT 60,
            auto_analyze INTEGER NOT NULL DEFAULT 0,
            enabled INTEGER NOT NULL DEFAULT 1,
            last_fetched_at TEXT,
            last_status TEXT NOT NULL DEFAULT '',
            last_error TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        );
        INSERT INTO sources
            (name, url, fetch_interval_minutes, created_at)
        VALUES ('Legacy', 'https://example.com/feed', 61, '2026-01-01T00:00:00+00:00');
        CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        INSERT INTO settings(key, value) VALUES('ai_prompt', '旧的全局规则');
        """
    )
    connection.commit()
    connection.close()

    migrated = Database(path).get_source(1)
    assert migrated["fetch_interval_hours"] == 2
    assert migrated["max_pages"] == 5
    assert migrated["auto_fetch_enabled"] == 1
    assert migrated["ai_prompt"] == "旧的全局规则"
