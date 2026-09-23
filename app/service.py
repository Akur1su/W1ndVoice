from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from app.ai import AIAnalyzer
from app.crawler import Crawler
from app.database import Database

logger = logging.getLogger(__name__)


class NewsService:
    def __init__(self, db: Database, crawler: Crawler, analyzer: AIAnalyzer) -> None:
        self.db = db
        self.crawler = crawler
        self.analyzer = analyzer
        self._locks: dict[int, asyncio.Lock] = {}

    async def fetch_source(self, source_id: int) -> dict[str, Any]:
        lock = self._locks.setdefault(source_id, asyncio.Lock())
        if lock.locked():
            return {"source_id": source_id, "status": "running", "changed": 0}
        async with lock:
            source = self.db.get_source(source_id)
            try:
                articles = await self.crawler.collect(source)
                changed_ids = self.db.save_articles(source_id, articles)
                analyzed = 0
                if source["auto_analyze"]:
                    for article_id in changed_ids[:5]:
                        try:
                            await self.analyzer.analyze(article_id)
                            analyzed += 1
                        except Exception as exc:  # noqa: BLE001
                            logger.warning("Automatic analysis failed for article %s: %s", article_id, exc)
                status = f"成功：发现 {len(articles)} 条，新增或更新 {len(changed_ids)} 条"
                if source["auto_analyze"] and len(changed_ids) > 5:
                    status += "；自动分析本轮限 5 条"
                self.db.update_source_status(source_id, status)
                return {
                    "source_id": source_id,
                    "status": "ok",
                    "found": len(articles),
                    "changed": len(changed_ids),
                    "analyzed": analyzed,
                }
            except Exception as exc:
                self.db.update_source_status(source_id, "抓取失败", str(exc))
                raise

    async def fetch_all(self) -> list[dict[str, Any]]:
        tasks = [self.fetch_source(source["id"]) for source in self.db.list_sources(True)]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return [
            result
            if isinstance(result, dict)
            else {"status": "error", "error": str(result)}
            for result in results
        ]

    async def fetch_due(self) -> None:
        now = datetime.now(UTC)
        due: list[int] = []
        for source in self.db.list_sources(True):
            if not source.get("auto_fetch_enabled", 1):
                continue
            if not source["last_fetched_at"]:
                due.append(source["id"])
                continue
            try:
                last = datetime.fromisoformat(source["last_fetched_at"])
            except ValueError:
                due.append(source["id"])
                continue
            if now >= last + timedelta(hours=source["fetch_interval_hours"]):
                due.append(source["id"])
        if due:
            await asyncio.gather(*(self.fetch_source(source_id) for source_id in due), return_exceptions=True)
