import sys
from pathlib import Path

from app.config import AppConfig
from app.database import Database


def test_frozen_build_uses_exe_directory_without_bundling_user_data(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "W1ndVoice.exe"))
    monkeypatch.delenv("W1NDVOICE_DATA_DIR", raising=False)

    config = AppConfig.from_env()

    assert config.data_dir == tmp_path
    assert config.data_dir.is_dir()


def test_explicit_data_dir_overrides_frozen_default(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "W1ndVoice.exe"))
    monkeypatch.setenv("W1NDVOICE_DATA_DIR", str(tmp_path / "custom"))

    assert AppConfig.from_env().data_dir == tmp_path / "custom"


def test_saved_port_is_used_on_next_start(tmp_path: Path, monkeypatch) -> None:
    database = Database(tmp_path / "w1ndvoice.db")
    database.set_settings({"server_port": "18080"})
    monkeypatch.setenv("W1NDVOICE_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("W1NDVOICE_PORT", raising=False)

    assert AppConfig.from_env().port == 18080


def test_environment_port_overrides_saved_port(tmp_path: Path, monkeypatch) -> None:
    database = Database(tmp_path / "w1ndvoice.db")
    database.set_settings({"server_port": "18080"})
    monkeypatch.setenv("W1NDVOICE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("W1NDVOICE_PORT", "19090")

    assert AppConfig.from_env().port == 19090
