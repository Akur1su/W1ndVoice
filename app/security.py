from __future__ import annotations

import ipaddress
import os
import socket
from pathlib import Path
from urllib.parse import urlparse

from cryptography.fernet import Fernet, InvalidToken


class SecretStore:
    def __init__(self, key_path: Path) -> None:
        self.key_path = key_path
        if not key_path.exists():
            key_path.write_bytes(Fernet.generate_key())
            try:
                os.chmod(key_path, 0o600)
            except OSError:
                pass
        self.fernet = Fernet(key_path.read_bytes().strip())

    def encrypt(self, value: str) -> str:
        return self.fernet.encrypt(value.encode()).decode() if value else ""

    def decrypt(self, value: str) -> str:
        if not value:
            return ""
        try:
            return self.fernet.decrypt(value.encode()).decode()
        except InvalidToken:
            return ""


def validate_public_url(url: str) -> str:
    parsed = urlparse(url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("仅支持完整的 http/https URL")
    if parsed.username or parsed.password:
        raise ValueError("URL 不能包含用户名或密码")

    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(parsed.hostname, parsed.port)}
    except socket.gaierror as exc:
        raise ValueError("域名无法解析") from exc

    for address in addresses:
        ip = ipaddress.ip_address(address)
        if any(
            (
                ip.is_private,
                ip.is_loopback,
                ip.is_link_local,
                ip.is_multicast,
                ip.is_reserved,
                ip.is_unspecified,
            )
        ):
            raise ValueError("出于安全原因，不能访问本机或内网地址")
    return parsed.geturl()
