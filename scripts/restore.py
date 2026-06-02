"""Restore a backup tar.gz produced by scripts/backup.py.

WARNING: This OVERWRITES current db/, memory/chroma/, data/photos/, and
company-config.yml. The current state is automatically backed up first
to backups/before-restore-<ts>.tar.gz unless --no-pre-backup.

Usage:
    .venv/bin/python scripts/restore.py backups/army-20260601-220000.tar.gz
    .venv/bin/python scripts/restore.py latest          # restores newest in backups/
    .venv/bin/python scripts/restore.py latest --no-pre-backup
"""
from __future__ import annotations

import argparse
import shutil
import sys
import tarfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
BACKUPS_DIR = REPO / "backups"

WIPE_PATHS = ["db", "memory/chroma", "data/photos"]


def find_latest() -> Path | None:
    if not BACKUPS_DIR.exists():
        return None
    backups = sorted(BACKUPS_DIR.glob("army-*.tar.gz"), reverse=True)
    return backups[0] if backups else None


def restore(archive: Path, do_pre_backup: bool = True) -> int:
    if not archive.exists():
        print(f"ERROR: {archive} not found", file=sys.stderr)
        return 1

    print(f"WARNING: about to overwrite current state from {archive.name}")
    print(f"  paths cleared: {', '.join(WIPE_PATHS)}")
    print(f"  + company-config.yml will be overwritten")
    if do_pre_backup:
        # Defer import to avoid running backup if user kills early
        from backup import make_backup
        print("  taking pre-restore backup first...")
        make_backup(tag="before-restore")

    confirm = input("type YES to proceed: ").strip()
    if confirm != "YES":
        print("aborted.")
        return 1

    # Wipe target dirs
    for rel in WIPE_PATHS:
        p = REPO / rel
        if p.exists():
            shutil.rmtree(p)

    # Extract
    with tarfile.open(archive, "r:gz") as tar:
        tar.extractall(REPO)

    print(f"✔ restored from {archive.name}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("archive", help="Path to backup tar.gz OR 'latest'")
    p.add_argument("--no-pre-backup", action="store_true",
                   help="Skip backing up current state before restore (risky)")
    args = p.parse_args()

    if args.archive == "latest":
        latest = find_latest()
        if not latest:
            print("ERROR: no backups found in backups/", file=sys.stderr)
            return 1
        archive = latest
        print(f"using latest: {archive.name}")
    else:
        archive = Path(args.archive).expanduser().resolve()

    return restore(archive, do_pre_backup=not args.no_pre_backup)


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    sys.exit(main())
