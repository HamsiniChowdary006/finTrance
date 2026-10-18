from pathlib import Path


def extract_pages(path: str | Path) -> list[str]:
    import fitz

    document = fitz.open(path)
    return [page.get_text() for page in document]


def extract_target_pages(path: str | Path, aliases: list[str], max_pages: int,
                         diagnostics: dict[str, object] | None = None) -> list[tuple[int, str]]:
    """Scan all page text, then return only relevant pages under the parse cap."""
    import fitz

    document = fitz.open(path)
    scanned = [(index + 1, page.get_text()) for index, page in enumerate(document)]
    terms = tuple(alias.casefold() for alias in aliases)
    matched = [(number, text) for number, text in scanned
               if any(term in text.casefold() for term in terms)]
    selected = scanned if len(scanned) <= max_pages else matched[:max_pages]
    if diagnostics is not None:
        diagnostics["pages"] = len(scanned)
        diagnostics["chars"] = sum(len(text) for _, text in scanned)
        diagnostics["aliases_matched"] = sorted(
            {alias for alias in aliases
             if any(alias.casefold() in text.casefold() for _, text in matched)})
        diagnostics["pages_parsed"] = len(selected)
    return selected
