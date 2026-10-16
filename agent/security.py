import ipaddress
import logging
import os
import re
import socket
from pathlib import Path
from urllib.parse import urlparse

import requests

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - dependency is declared
    load_dotenv = None


KEY_RE = re.compile(r"(?i)(authorization\s*:\s*bearer\s+|(?:api[_-]?key|secret|token|password)\s*[:=]\s*)\S+")


class RedactionFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = KEY_RE.sub(r"\1[REDACTED]", record.getMessage())
        record.args = ()
        return True


def configure_environment() -> None:
    if load_dotenv:
        load_dotenv()


def require_key(name: str) -> str:
    configure_environment()
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Required provider key {name} is missing; set it in the environment")
    return value


def safe_path(path: str | Path, root: str | Path) -> Path:
    root_path = Path(root).resolve()
    candidate = Path(path)
    resolved = candidate.resolve()
    if root_path != resolved and root_path not in resolved.parents:
        raise ValueError("path escapes configured root")
    if candidate.is_symlink() and root_path not in candidate.resolve().parents:
        raise ValueError("symlink escapes configured root")
    return resolved


def _public_host(host: str) -> bool:
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(host, None)}
    except socket.gaierror as error:
        raise ValueError(f"host cannot be resolved: {host}") from error
    return all(ipaddress.ip_address(address).is_global for address in addresses)


class SafeHTTP:
    def __init__(self, allowed_domains: set[str], max_bytes: int = 20_000_000):
        self.allowed_domains = allowed_domains
        self.max_bytes = max_bytes
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "finTrance-research/0.1"})

    def get(self, url: str, *, referer: str | None = None) -> bytes:
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname not in self.allowed_domains:
            raise ValueError("URL is not HTTPS or its domain is not allowlisted")
        if not _public_host(parsed.hostname):
            raise ValueError("private or loopback destination blocked")
        headers = {"Referer": referer} if referer else {}
        response = self.session.get(url, headers=headers, timeout=(5, 30),
                                    allow_redirects=False, stream=True)
        response.raise_for_status()
        content_length = int(response.headers.get("Content-Length", "0"))
        if content_length > self.max_bytes:
            raise ValueError("response exceeds configured size limit")
        content = bytearray()
        for chunk in response.iter_content(64 * 1024):
            content.extend(chunk)
            if len(content) > self.max_bytes:
                raise ValueError("response exceeds configured size limit")
        return bytes(content)
