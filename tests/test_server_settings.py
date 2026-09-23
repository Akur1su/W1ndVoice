from pathlib import Path

from bs4 import BeautifulSoup
from fastapi.testclient import TestClient

from app import main
from app.database import Database


def test_port_setting_is_saved_and_requires_restart(tmp_path: Path, monkeypatch) -> None:
    database = Database(tmp_path / "settings.db")
    monkeypatch.setattr(main, "db", database)
    monkeypatch.setattr(main.analyzer, "db", database)
    monkeypatch.delenv("W1NDVOICE_PORT", raising=False)
    client = TestClient(main.app)

    initial = client.get("/api/settings/server")
    assert initial.status_code == 200
    assert initial.json()["current_port"] == main.config.port

    saved = client.put("/api/settings/server", json={"port": 18080})
    assert saved.status_code == 200
    assert saved.json()["configured_port"] == 18080
    assert saved.json()["restart_required"] is (main.config.port != 18080)
    assert database.get_settings()["server_port"] == "18080"

    page = BeautifulSoup(client.get("/settings/server").text, "html.parser")
    assert page.select_one('#server-form input[name="port"]')["value"] == "18080"
    assert client.put("/api/settings/server", json={"port": 70000}).status_code == 422
