"""Document parsers.

Each parser exposes `parse(path_or_url, **kwargs) -> str`.
Format detection lives in RAGNAR, not here.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from capabilities.parsers import docx, image, pdf, pptx, url, xlsx

# Extension → parser callable. URL handled separately (no extension).
EXT_PARSERS: dict[str, Callable[[Path], str]] = {
    ".pdf": pdf.parse,
    ".docx": docx.parse,
    ".pptx": pptx.parse,
    ".xlsx": xlsx.parse,
    ".png": image.parse,
    ".jpg": image.parse,
    ".jpeg": image.parse,
    ".webp": image.parse,
}

# Format names (for RawDocument.format)
EXT_FORMATS: dict[str, str] = {
    ".pdf": "pdf",
    ".docx": "docx",
    ".pptx": "pptx",
    ".xlsx": "xlsx",
    ".png": "image",
    ".jpg": "image",
    ".jpeg": "image",
    ".webp": "image",
}


def parse_url(url_str: str) -> str:
    return url.parse(url_str)
