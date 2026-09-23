import socket

import pytest

from app import security


def test_rejects_private_address() -> None:
    with pytest.raises(ValueError, match="内网"):
        security.validate_public_url("http://127.0.0.1/admin")


def test_accepts_public_resolution(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))],
    )
    assert security.validate_public_url("https://example.com/news") == "https://example.com/news"
