from pathlib import Path

import httpx
import pytest

from app.database import Database
from app.service import NewsService


class FakeDatabase:
    def list_sources(self, _enabled_only: bool):
        return [
            {
                "id": 1,
                "auto_fetch_enabled": 0,
                "last_fetched_at": None,
                "fetch_interval_hours": 1,
            },
            {
                "id": 2,
                "auto_fetch_enabled": 1,
                "last_fetched_at": None,
                "fetch_interval_hours": 1,
            },
        ]


@pytest.mark.asyncio
async def test_scheduler_skips_manual_only_sources() -> None:
    service = NewsService(FakeDatabase(), object(), object())  # type: ignore[arg-type]
    fetched: list[int] = []

    async def record_fetch(source_id: int):
        fetched.append(source_id)
        return {"source_id": source_id}

    service.fetch_source = record_fetch  # type: ignore[method-assign]
    await service.fetch_due()
    assert fetched == [2]


@pytest.mark.asyncio
async def test_failed_fetch_keeps_source_and_records_useful_error(tmp_path: Path) -> None:
    class FailingCrawler:
        async def collect(self, _source):
            raise httpx.ConnectError("")

    db = Database(tmp_path / "failed.db")
    source = db.add_source(
        {
            "name": "GitHub", "url": "https://api.github.com/advisories",
            "category": "漏洞", "kind": "json", "fetch_interval_hours": 1,
        }
    )
    service = NewsService(db, FailingCrawler(), object())  # type: ignore[arg-type]
    with pytest.raises(httpx.ConnectError):
        await service.fetch_source(source["id"])
    saved = db.get_source(source["id"])
    assert saved["last_status"] == "抓取失败"
    assert "网络或代理" in saved["last_error"]
