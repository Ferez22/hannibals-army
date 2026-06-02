"""Backup all stateful files into a date-stamped tar.gz under backups/.

Includes:
  - db/                  (sqlite graph)
  - memory/chroma/       (vector store)
  - company-config.yml   (canonical company state)
  - data/photos/         (person photos)
  - digital-twin-config.yml (owner profile, if present)
  - .env                 (only if --include-env, off by default — has secrets)

Usage:
    .venv/bin/python scripts/backup.py
    .venv/bin/python scripts/backup.py --include-env
    .venv/bin/python scripts/backup.py --tag "before-9.2-rebuild"
"""
from __future__ import annotations

import argparse
import sys
import tarfile
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
BACKUPS_DIR = REPO / "backups"

DEFAULT_PATHS = [
    "db",
    "memory/chroma",
    "company-config.yml",
    "data/photos",
    "digital-twin-config.yml",
]
SECRET_PATHS = [".env", "google_credentials.json", "google_token.json"]


def make_backup(include_env: bool = False, tag: str = "") -> Path:
    BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    fname = f"army-{ts}"
    if tag:
        safe_tag = "".join(c if c.isalnum() or c in "-_" else "_" for c in tag)
        fname += f"-{safe_tag}"
    fname += ".tar.gz"
    out_path = BACKUPS_DIR / fname

    paths_to_archive = list(DEFAULT_PATHS)
    if include_env:
        paths_to_archive.extend(SECRET_PATHS)

    added: list[str] = []
    skipped: list[str] = []
    with tarfile.open(out_path, "w:gz") as tar:
        for rel in paths_to_archive:
            src = REPO / rel
            if not src.exists():
                skipped.append(rel)
                continue
            tar.add(src, arcname=rel)
            added.append(rel)

    print(f"✔ backup: {out_path.relative_to(REPO)}")
    print(f"  size: {out_path.stat().st_size / 1024:.1f} KB")
    print(f"  added: {', '.join(added) if added else '—'}")
    if skipped:
        print(f"  skipped (not present): {', '.join(skipped)}")
    return out_path


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--include-env", action="store_true",
                   help="Also archive .env and google_*.json (contains secrets — store securely)")
    p.add_argument("--tag", default="", help="Tag appended to filename (e.g. 'before-9.2')")
    args = p.parse_args()
    make_backup(include_env=args.include_env, tag=args.tag)
    return 0


if __name__ == "__main__":
    sys.exit(main())
