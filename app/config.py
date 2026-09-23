from __future__ import annotations

import os
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AppConfig:
    data_dir: Path
    host: str
    port: int
    log_level: str

    @staticmethod
    def stored_port(data_dir: Path) -> int | None:
        database_path = data_dir / "w1ndvoice.db"
        if not database_path.is_file():
            return None
        try:
            with sqlite3.connect(f"file:{database_path}?mode=ro", uri=True) as database:
                row = database.execute(
                    "SELECT value FROM settings WHERE key = 'server_port'"
                ).fetchone()
            port = int(row[0]) if row else None
            return port if port is not None and 1024 <= port <= 65535 else None
        except (sqlite3.Error, ValueError):
            return None

    @classmethod
    def from_env(cls) -> AppConfig:
        configured_dir = os.getenv("W1NDVOICE_DATA_DIR")
        if configured_dir:
            data_dir = Path(configured_dir).resolve()
        elif getattr(sys, "frozen", False):
            data_dir = Path(sys.executable).resolve().parent
        else:
            data_dir = Path("./data").resolve()
        data_dir.mkdir(parents=True, exist_ok=True)
        environment_port = os.getenv("W1NDVOICE_PORT")
        port = int(environment_port) if environment_port is not None else cls.stored_port(data_dir)
        if port is None:
            port = 8000
        if not 1 <= port <= 65535:
            raise ValueError("W1NDVOICE_PORT 必须在 1 到 65535 之间")
        return cls(
            data_dir=data_dir,
            host=os.getenv("W1NDVOICE_HOST", "127.0.0.1"),
            port=port,
            log_level=os.getenv("W1NDVOICE_LOG_LEVEL", "INFO"),
        )
