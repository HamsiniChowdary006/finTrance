import hashlib
import json
import time
from abc import ABC, abstractmethod
from pathlib import Path

import requests

from agent.security import SafeHTTP, safe_path
from schemas.models import CompanyProfile, DocRef, Document


class Source(ABC):
    @abstractmethod
    def search(self, profile: CompanyProfile) -> list[DocRef]:
        ...

    @abstractmethod
    def fetch(self, doc: DocRef) -> Path:
        ...


class Cache:
    def __init__(self, root: str | Path = "store/cache",
                 allowed_domains: set[str] | None = None):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.root = self.root.resolve()
        self.http = SafeHTTP(allowed_domains or {"www.bseindia.com", "www.nseindia.com",
                                                  "www.crisil.com"})
        self.last_request: dict[str, float] = {}

    def download(self, url: str, ticker: str) -> tuple[Path, str]:
        host = requests.utils.urlparse(url).netloc
        index = self.root / ticker / "index.json"
        entries = json.loads(index.read_text(encoding="utf-8")) if index.exists() else {}
        if url in entries and Path(entries[url]).exists():
            cached = Path(entries[url])
            return cached, cached.name
        wait = 1.0 - (time.monotonic() - self.last_request.get(host, 0))
        if wait > 0:
            time.sleep(wait)
        content = self.http.get(url)
        self.last_request[host] = time.monotonic()
        digest = hashlib.sha256(content).hexdigest()
        target = safe_path(self.root / ticker / digest, self.root)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        entries[url] = str(target)
        index.write_text(json.dumps(entries, indent=2), encoding="utf-8")
        return target, digest

    @staticmethod
    def document(doc: DocRef, path: Path, digest: str) -> Document:
        return Document(doc_id=digest[:16], ticker=doc.ticker, source_type=doc.source_type,
                        title=doc.title, url=str(doc.url) if doc.url else None,
                        published=doc.published, sha256=digest, local_path=str(path))
