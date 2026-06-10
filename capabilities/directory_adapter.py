"""Directory adapter — generic interface for company org-chart sources.

Phase 11A ships with CSV + JSON file adapters. Phase 11A.next will add a Google
Workspace adapter behind the same `DirectoryEntry` schema, so callers (`scripts/
import_directory.py`) work unchanged when the data source swaps.

CSV / JSON columns expected (column names are case-insensitive, snake_case
preferred):
  email           required — primary identifier; used for dedup against
                  `Person.emails`
  name            required — full display name
  title           optional — job title; drives tier mapping via
                  `config.TIER_TITLE_RULES`
  department      optional — free-form ("Engineering", "Sales")
  manager_email   optional — email of the reporting manager; used to create
                  MEMBER_OF edge after all rows are imported
  tier            optional — explicit tier override (one of `config.TIERS`).
                  When present, takes precedence over title-based mapping.

The adapter never touches the KG directly. It returns a list of normalized
`DirectoryEntry` dicts; callers decide promotion + edge wiring.
"""
from __future__ import annotations

import csv
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

log = logging.getLogger("hannibal.directory")


@dataclass(frozen=True)
class DirectoryEntry:
    email: str
    name: str
    title: str | None = None
    department: str | None = None
    manager_email: str | None = None
    tier_override: str | None = None  # raw tier string; validated downstream


def read_directory(path: str | Path) -> list[DirectoryEntry]:
    """Dispatch on file extension. Return [] on missing/empty file."""
    p = Path(path)
    if not p.exists():
        log.warning("directory_file_missing", extra={"path": str(p)})
        return []
    suffix = p.suffix.lower()
    if suffix == ".csv":
        entries = list(_read_csv(p))
    elif suffix == ".json":
        entries = list(_read_json(p))
    else:
        raise ValueError(f"unsupported directory file: {p.suffix} (need .csv or .json)")
    log.info("directory_loaded", extra={"path": str(p), "count": len(entries)})
    return entries


def _read_csv(path: Path) -> Iterator[DirectoryEntry]:
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            entry = _row_to_entry({k.strip().lower(): (v or "").strip() for k, v in row.items()})
            if entry:
                yield entry


def _read_json(path: Path) -> Iterator[DirectoryEntry]:
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError("JSON directory must be a list of objects")
    for raw in data:
        if not isinstance(raw, dict):
            continue
        norm = {str(k).strip().lower(): (str(v).strip() if v is not None else "") for k, v in raw.items()}
        entry = _row_to_entry(norm)
        if entry:
            yield entry


def _row_to_entry(row: dict[str, str]) -> DirectoryEntry | None:
    email = row.get("email") or row.get("primaryemail") or ""
    name = row.get("name") or row.get("fullname") or ""
    if not email or not name:
        log.info("directory_row_skipped_missing_required", extra={"row": row})
        return None
    return DirectoryEntry(
        email=email.lower(),
        name=name,
        title=row.get("title") or row.get("job_title") or None,
        department=row.get("department") or row.get("dept") or None,
        manager_email=(row.get("manager_email") or row.get("manager") or "").lower() or None,
        tier_override=row.get("tier") or None,
    )
