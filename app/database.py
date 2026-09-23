from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.init_schema()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def init_schema(self) -> None:
        with self.connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS sources (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    url TEXT NOT NULL UNIQUE,
                    category TEXT NOT NULL DEFAULT '技术',
                    kind TEXT NOT NULL DEFAULT 'auto',
                    item_selector TEXT NOT NULL DEFAULT '',
                    fetch_interval_hours INTEGER NOT NULL DEFAULT 1,
                    max_pages INTEGER NOT NULL DEFAULT 5,
                    auto_fetch_enabled INTEGER NOT NULL DEFAULT 1,
                    auto_analyze INTEGER NOT NULL DEFAULT 0,
                    ai_prompt TEXT NOT NULL DEFAULT '',
                    enabled INTEGER NOT NULL DEFAULT 1,
                    last_fetched_at TEXT,
                    last_status TEXT NOT NULL DEFAULT '等待首次抓取',
                    last_error TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS articles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_id INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
                    title TEXT NOT NULL,
                    url TEXT NOT NULL UNIQUE,
                    author TEXT NOT NULL DEFAULT '',
                    published_at TEXT,
                    fetched_at TEXT NOT NULL,
                    content TEXT NOT NULL DEFAULT '',
                    content_hash TEXT NOT NULL,
                    summary TEXT NOT NULL DEFAULT '',
                    importance INTEGER,
                    tags_json TEXT NOT NULL DEFAULT '[]',
                    risk_level TEXT NOT NULL DEFAULT '',
                    ai_status TEXT NOT NULL DEFAULT 'idle',
                    ai_error TEXT NOT NULL DEFAULT '',
                    analyzed_at TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_articles_published
                    ON articles(published_at DESC, fetched_at DESC);
                CREATE INDEX IF NOT EXISTS idx_articles_source ON articles(source_id);

                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                """
            )
            columns = {
                row["name"] for row in db.execute("PRAGMA table_info(sources)").fetchall()
            }
            if "fetch_interval_hours" not in columns:
                db.execute(
                    "ALTER TABLE sources ADD COLUMN fetch_interval_hours INTEGER NOT NULL DEFAULT 1"
                )
                if "fetch_interval_minutes" in columns:
                    db.execute(
                        """
                        UPDATE sources
                        SET fetch_interval_hours = MAX(
                            1, CAST((fetch_interval_minutes + 59) / 60 AS INTEGER)
                        )
                        """
                    )
            if "max_pages" not in columns:
                db.execute("ALTER TABLE sources ADD COLUMN max_pages INTEGER NOT NULL DEFAULT 5")
            if "auto_fetch_enabled" not in columns:
                db.execute(
                    "ALTER TABLE sources ADD COLUMN auto_fetch_enabled INTEGER NOT NULL DEFAULT 1"
                )
            if "ai_prompt" not in columns:
                db.execute("ALTER TABLE sources ADD COLUMN ai_prompt TEXT NOT NULL DEFAULT ''")
                previous_prompt = db.execute(
                    "SELECT value FROM settings WHERE key = 'ai_prompt'"
                ).fetchone()
                if previous_prompt and previous_prompt["value"]:
                    db.execute(
                        "UPDATE sources SET ai_prompt = ? WHERE ai_prompt = ''",
                        (previous_prompt["value"],),
                    )

    def add_source(self, source: dict[str, Any]) -> dict[str, Any]:
        with self.connect() as db:
            cursor = db.execute(
                """
                INSERT INTO sources
                    (name, url, category, kind, item_selector, fetch_interval_hours,
                     max_pages, auto_fetch_enabled, auto_analyze, ai_prompt, enabled, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source["name"],
                    source["url"],
                    source["category"],
                    source["kind"],
                    source.get("item_selector", ""),
                    source["fetch_interval_hours"],
                    source.get("max_pages", 5),
                    int(source.get("auto_fetch_enabled", True)),
                    int(source.get("auto_analyze", False)),
                    source.get("ai_prompt", ""),
                    int(source.get("enabled", True)),
                    utc_now(),
                ),
            )
            source_id = cursor.lastrowid
        return self.get_source(int(source_id))

    def get_source(self, source_id: int) -> dict[str, Any]:
        with self.connect() as db:
            row = db.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone()
        if not row:
            raise KeyError(source_id)
        return dict(row)

    def update_source(self, source_id: int, source: dict[str, Any]) -> dict[str, Any]:
        with self.connect() as db:
            cursor = db.execute(
                """
                UPDATE sources SET
                    name=?, url=?, category=?, kind=?, item_selector=?,
                    fetch_interval_hours=?, max_pages=?, auto_fetch_enabled=?,
                    auto_analyze=?, ai_prompt=?, enabled=?,
                    last_fetched_at=NULL, last_status='配置已更新，等待抓取', last_error=''
                WHERE id=?
                """,
                (
                    source["name"],
                    source["url"],
                    source["category"],
                    source["kind"],
                    source.get("item_selector", ""),
                    source["fetch_interval_hours"],
                    source.get("max_pages", 5),
                    int(source.get("auto_fetch_enabled", True)),
                    int(source.get("auto_analyze", False)),
                    source.get("ai_prompt", ""),
                    int(source.get("enabled", True)),
                    source_id,
                ),
            )
            if cursor.rowcount == 0:
                raise KeyError(source_id)
        return self.get_source(source_id)

    def list_sources(self, enabled_only: bool = False) -> list[dict[str, Any]]:
        query = "SELECT * FROM sources"
        if enabled_only:
            query += " WHERE enabled = 1"
        query += " ORDER BY created_at DESC"
        with self.connect() as db:
            return [dict(row) for row in db.execute(query).fetchall()]

    def delete_source(self, source_id: int) -> bool:
        with self.connect() as db:
            cursor = db.execute("DELETE FROM sources WHERE id = ?", (source_id,))
            return cursor.rowcount > 0

    def update_source_status(self, source_id: int, status: str, error: str = "") -> None:
        with self.connect() as db:
            db.execute(
                """UPDATE sources
                   SET last_fetched_at = ?, last_status = ?, last_error = ? WHERE id = ?""",
                (utc_now(), status, error[:1000], source_id),
            )

    def save_articles(self, source_id: int, articles: list[dict[str, Any]]) -> list[int]:
        changed_ids: list[int] = []
        with self.connect() as db:
            for article in articles:
                old = db.execute(
                    "SELECT id, content_hash FROM articles WHERE url = ?", (article["url"],)
                ).fetchone()
                if old and old["content_hash"] == article["content_hash"]:
                    continue
                if old:
                    db.execute(
                        """
                        UPDATE articles SET source_id=?, title=?, author=?, published_at=?,
                            fetched_at=?, content=?, content_hash=?, ai_status='idle',
                            ai_error='', summary='', importance=NULL, tags_json='[]', risk_level=''
                        WHERE id=?
                        """,
                        (
                            source_id,
                            article["title"],
                            article.get("author", ""),
                            article.get("published_at"),
                            utc_now(),
                            article.get("content", ""),
                            article["content_hash"],
                            old["id"],
                        ),
                    )
                    changed_ids.append(int(old["id"]))
                else:
                    cursor = db.execute(
                        """
                        INSERT INTO articles
                            (source_id, title, url, author, published_at, fetched_at,
                             content, content_hash)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            source_id,
                            article["title"],
                            article["url"],
                            article.get("author", ""),
                            article.get("published_at"),
                            utc_now(),
                            article.get("content", ""),
                            article["content_hash"],
                        ),
                    )
                    changed_ids.append(int(cursor.lastrowid))
        return changed_ids

    def list_articles(
        self, limit: int = 100, category: str = "", query: str = ""
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if category:
            clauses.append("s.category = ?")
            params.append(category)
        if query:
            clauses.append("(a.title LIKE ? OR a.content LIKE ? OR a.summary LIKE ?)")
            needle = f"%{query}%"
            params.extend([needle, needle, needle])
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        params.append(min(max(limit, 1), 500))
        sql = f"""
            SELECT a.*, s.name AS source_name, s.category
            FROM articles a JOIN sources s ON s.id = a.source_id
            {where}
            ORDER BY COALESCE(a.published_at, a.fetched_at) DESC
            LIMIT ?
        """
        with self.connect() as db:
            rows = [dict(row) for row in db.execute(sql, params).fetchall()]
        for row in rows:
            row["tags"] = json.loads(row.pop("tags_json") or "[]")
        return rows

    def get_article(self, article_id: int) -> dict[str, Any]:
        with self.connect() as db:
            row = db.execute("SELECT * FROM articles WHERE id = ?", (article_id,)).fetchone()
        if not row:
            raise KeyError(article_id)
        result = dict(row)
        result["tags"] = json.loads(result.pop("tags_json") or "[]")
        return result

    def delete_article(self, article_id: int) -> bool:
        with self.connect() as db:
            cursor = db.execute("DELETE FROM articles WHERE id = ?", (article_id,))
            return cursor.rowcount > 0

    def mark_ai_running(self, article_id: int) -> None:
        with self.connect() as db:
            db.execute(
                "UPDATE articles SET ai_status='running', ai_error='' WHERE id=?", (article_id,)
            )

    def save_analysis(self, article_id: int, analysis: dict[str, Any]) -> None:
        with self.connect() as db:
            db.execute(
                """
                UPDATE articles SET summary=?, importance=?, tags_json=?, risk_level=?,
                    ai_status='done', ai_error='', analyzed_at=? WHERE id=?
                """,
                (
                    analysis["summary"],
                    analysis["importance"],
                    json.dumps(analysis["tags"], ensure_ascii=False),
                    analysis["risk_level"],
                    utc_now(),
                    article_id,
                ),
            )

    def save_ai_error(self, article_id: int, error: str) -> None:
        with self.connect() as db:
            db.execute(
                "UPDATE articles SET ai_status='failed', ai_error=? WHERE id=?",
                (error[:1000], article_id),
            )

    def get_settings(self) -> dict[str, str]:
        with self.connect() as db:
            return {row["key"]: row["value"] for row in db.execute("SELECT * FROM settings")}

    def set_settings(self, values: dict[str, str]) -> None:
        with self.connect() as db:
            db.executemany(
                """INSERT INTO settings(key, value) VALUES(?, ?)
                   ON CONFLICT(key) DO UPDATE SET value=excluded.value""",
                values.items(),
            )

    def stats(self) -> dict[str, int]:
        with self.connect() as db:
            sources = db.execute("SELECT COUNT(*) FROM sources").fetchone()[0]
            articles = db.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
            analyzed = db.execute(
                "SELECT COUNT(*) FROM articles WHERE ai_status='done'"
            ).fetchone()[0]
        return {"sources": sources, "articles": articles, "analyzed": analyzed}
