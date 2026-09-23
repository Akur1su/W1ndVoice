from pathlib import Path

from bs4 import BeautifulSoup
from fastapi.testclient import TestClient

from app import main
from app.database import Database


def test_navigation_uses_real_pages_and_shows_only_selected_view(tmp_path: Path, monkeypatch) -> None:
    database = Database(tmp_path / "navigation.db")
    monkeypatch.setattr(main, "db", database)
    monkeypatch.setattr(main.analyzer, "db", database)
    client = TestClient(main.app)

    expected = {
        "/": "home",
        "/sources": "sources",
        "/settings/ai": "ai",
        "/settings/server": "server",
        "/stream": "stream",
    }
    for path, selected in expected.items():
        response = client.get(path)
        assert response.status_code == 200
        page = BeautifulSoup(response.text, "html.parser")
        assert page.select_one('.brand[aria-label="W1ndVoice 首页"]')["href"] == "/"
        assert page.select_one(".nav-stream") is None
        assert page.select_one(".home-stream-card")["href"] == "/stream"
        assert {link["href"] for link in page.select(".settings-dropdown a")} == {
            "/sources", "/settings/ai", "/settings/server"
        }
        for view, section in ((node["data-view"], node) for node in page.select(".page-view")):
            assert section.has_attr("hidden") is (view != selected)
        if selected != "home":
            assert page.select_one(f'[data-view="{selected}"] .back-home')["href"] == "/"
