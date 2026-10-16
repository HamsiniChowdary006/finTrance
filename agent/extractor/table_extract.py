from pathlib import Path


def extract_tables(path: str | Path) -> list[list[list[str]]]:
    import pdfplumber

    with pdfplumber.open(path) as pdf:
        return [table for page in pdf.pages for table in (page.extract_tables() or [])]
