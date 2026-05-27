"""PDF parser via PyMuPDF (fitz)."""
from __future__ import annotations

from pathlib import Path


def parse(path: Path) -> str:
    import pymupdf

    parts: list[str] = []
    with pymupdf.open(path) as doc:
        for page in doc:
            parts.append(page.get_text())
    return "\n".join(parts)
