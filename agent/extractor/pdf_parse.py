from pathlib import Path


def extract_pages(path: str | Path) -> list[str]:
    import fitz

    document = fitz.open(path)
    return [page.get_text() for page in document]
