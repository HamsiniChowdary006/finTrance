from pathlib import Path

from agent.security import safe_path
from schemas.models import CompanyProfile, DocRef, SourceType

from .base import Source


class ManualDropSource(Source):
    def __init__(self, root: str | Path = "store/manual_drop"):
        self.root = Path(root)

    def search(self, profile: CompanyProfile) -> list[DocRef]:
        ticker = profile.symbol or profile.name
        folder = safe_path(self.root / ticker, self.root)
        paths = sorted(folder.glob("*")) if folder.exists() else []
        return [DocRef(ticker=ticker, source_type=SourceType.MANUAL, title=path.name,
                       local_path=path) for path in paths
                if path.is_file() and path.suffix.casefold() in {".pdf", ".html", ".htm", ".xlsx"}]

    def fetch(self, doc: DocRef) -> Path:
        if not doc.local_path:
            raise ValueError("Manual document has no local path")
        return doc.local_path
