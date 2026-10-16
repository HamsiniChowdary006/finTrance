from pathlib import Path

from schemas.models import CompanyProfile, DocRef

from .base import Cache, Source


class ExchangeSource(Source):
    """Exchange adapter boundary; URLs are injected, never guessed."""

    def __init__(self, cache: Cache | None = None, endpoint: str | None = None):
        self.cache = cache or Cache()
        self.endpoint = endpoint

    def search(self, profile: CompanyProfile) -> list[DocRef]:
        if not self.endpoint:
            return []
        return []

    def fetch(self, doc: DocRef) -> Path:
        if not doc.url:
            raise ValueError("Exchange document has no verified URL")
        return self.cache.download(str(doc.url), doc.ticker)[0]
