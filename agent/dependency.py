import re
from dataclasses import dataclass

from agent.extractor.document import read_document
from schemas.models import Document


@dataclass(frozen=True)
class DependencyMention:
    document_id: str
    page: int
    quote: str
    matched_alias: str


def find_cross_company_mentions(target_aliases: list[str], documents: list[Document],
                                budget: int = 20) -> list[DependencyMention]:
    mentions: list[DependencyMention] = []
    for document in documents:
        try:
            text = read_document(document.local_path)
        except (OSError, ValueError, RuntimeError):
            continue
        for alias in target_aliases:
            match = re.search(re.escape(alias), text, re.IGNORECASE)
            if match:
                start = max(0, match.start() - 140)
                end = min(len(text), match.end() + 140)
                mentions.append(DependencyMention(document.doc_id, 1, text[start:end].strip(), alias))
                if len(mentions) >= budget:
                    return mentions
    return mentions
