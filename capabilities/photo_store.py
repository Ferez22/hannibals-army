"""Photo storage — copy local files OR download URLs into data/photos/.

Returns relative path stored on Person.fields.photo_path.
"""
from __future__ import annotations

import logging
import re
import shutil
from pathlib import Path
from urllib.parse import urlparse

import config

log = logging.getLogger("hannibal.photo_store")

PHOTO_DIR = config.REPO_ROOT / "data" / "photos"
ALLOWED_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


def attach_photo(person_id: str, source: str) -> Path:
    """Save photo for person. Source = local path OR http(s) URL.

    Returns path under data/photos/. Raises ValueError on bad input.
    """
    PHOTO_DIR.mkdir(parents=True, exist_ok=True)
    source = source.strip()
    if not source:
        raise ValueError("empty source")

    if source.startswith(("http://", "https://")):
        path = _download(person_id, source)
    else:
        path = _copy_local(person_id, source)

    log.info("photo_attached", extra={"person_id": person_id, "path": str(path)})
    return path


def get_photo_path(photo_field: str | None) -> Path | None:
    """Resolve stored relative path back to absolute. Returns None if missing."""
    if not photo_field:
        return None
    p = config.REPO_ROOT / photo_field
    return p if p.exists() else None


def _copy_local(person_id: str, source: str) -> Path:
    src = Path(source).expanduser().resolve()
    if not src.exists():
        raise ValueError(f"file not found: {src}")
    ext = src.suffix.lower()
    if ext not in ALLOWED_EXTS:
        raise ValueError(f"unsupported extension {ext}. Allowed: {sorted(ALLOWED_EXTS)}")
    dst = PHOTO_DIR / f"{person_id}{ext}"
    _remove_existing(person_id)
    shutil.copy2(src, dst)
    return dst.relative_to(config.REPO_ROOT)


def _download(person_id: str, url: str) -> Path:
    import requests

    parsed = urlparse(url)
    ext = Path(parsed.path).suffix.lower()
    if ext not in ALLOWED_EXTS:
        ext = ".jpg"  # default guess
    resp = requests.get(url, timeout=15, stream=True)
    resp.raise_for_status()
    ct = resp.headers.get("content-type", "")
    if ct and not ct.startswith("image/"):
        raise ValueError(f"URL did not return an image (content-type: {ct})")
    dst = PHOTO_DIR / f"{person_id}{ext}"
    _remove_existing(person_id)
    with dst.open("wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            f.write(chunk)
    return dst.relative_to(config.REPO_ROOT)


def _remove_existing(person_id: str) -> None:
    """Remove any previously stored photo for this person, regardless of extension."""
    for old in PHOTO_DIR.glob(f"{re.escape(person_id)}.*"):
        try:
            old.unlink()
        except OSError:
            pass
