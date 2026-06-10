"""CLI — bootstrap the company org chart from a CSV / JSON directory file.

Usage:
    .venv/bin/python scripts/import_directory.py path/to/directory.csv

CSV / JSON shape: see `capabilities/directory_adapter.py` docstring.

Idempotent — existing Persons matched by email get patched in place; new ones
are added unconfirmed (Audit screen visible). Reporting edges (MEMBER_OF with
`role='direct_report'`) are wired after the upsert pass so manager_email
references resolve.
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# Allow `from capabilities import ...` when invoked as a script
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from capabilities import directory_adapter, directory_import  # noqa: E402
from core.ingestion_pipeline import get_kg  # noqa: E402

log = logging.getLogger("hannibal.import_directory_cli")


def main() -> int:
    parser = argparse.ArgumentParser(description="Import org chart from CSV / JSON.")
    parser.add_argument("path", help="path to directory.csv or directory.json")
    parser.add_argument("--dry-run", action="store_true",
                        help="parse + log entries without writing to KG")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

    entries = directory_adapter.read_directory(args.path)
    if not entries:
        print(f"no entries parsed from {args.path}")
        return 1

    print(f"parsed {len(entries)} directory entries")
    for e in entries:
        print(f"  • {e.email:35} {e.name:30} {e.title or '—':25} manager={e.manager_email or '—'}")

    if args.dry_run:
        print("\n--dry-run: nothing written")
        return 0

    kg = get_kg()
    result = directory_import.import_directory(kg, entries)
    print("\nImport result:")
    print(f"  created:            {result.created}")
    print(f"  updated:            {result.updated}")
    print(f"  skipped:            {result.skipped}")
    print(f"  manager_edges_added:{result.manager_edges_added}")
    if result.errors:
        print(f"  errors:             {len(result.errors)}")
        for err in result.errors:
            print(f"    - {err}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
