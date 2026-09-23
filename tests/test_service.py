import pytest

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
