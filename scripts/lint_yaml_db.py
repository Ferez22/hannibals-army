"""Detect drift between company-config.yml (canonical mirror) and live KG (db/graph.db).

Reports:
  - Section count mismatches (yaml has N rows, DB has M)
  - Names present in yaml but not DB (orphan yaml entries)
  - Names present in DB but not yaml (sync gap)
  - Field divergence on entries that match by name (yaml says role=X, DB says role=Y)

Exits non-zero if any mismatch found — usable in CI.

Usage:
    .venv/bin/python scripts/lint_yaml_db.py
    .venv/bin/python scripts/lint_yaml_db.py --section people     # check one section only
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from capabilities import yaml_io
from core.knowledge_graph import KnowledgeGraph

SECTIONS = ["teams", "people", "projects", "clients", "rules", "recent_events"]
ENTITY_TYPE = {
    "teams":    "Team",
    "people":   "Person",
    "projects": "Project",
    "clients":  "Client",
    "rules":    "Rule",
    "recent_events": "Event",
}
NAME_KEY = {
    "teams":    "name",
    "people":   "name",
    "projects": "name",
    "clients":  "name",
    "rules":    "title",
    "recent_events": "name",
}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--section", choices=SECTIONS, help="Only check one section")
    args = p.parse_args()

    yaml_path = config.REPO_ROOT / "company-config.yml"
    if not yaml_path.exists():
        print(f"ERROR: {yaml_path} does not exist", file=sys.stderr)
        return 2

    data = yaml_io.read_yaml(yaml_path)
    kg = KnowledgeGraph()
    kg.init()

    sections = [args.section] if args.section else SECTIONS
    total_findings = 0

    for section in sections:
        findings = _check_section(data, kg, section)
        if findings:
            total_findings += len(findings)
            print(f"\n[{section}] {len(findings)} finding(s):")
            for f in findings:
                print(f"  {f}")
        else:
            print(f"[{section}] ✔ clean")

    print()
    if total_findings == 0:
        print(f"✔ no drift across {len(sections)} section(s)")
        return 0
    print(f"⚠ {total_findings} total finding(s)")
    return 1


def _check_section(data: dict, kg: KnowledgeGraph, section: str) -> list[str]:
    findings: list[str] = []
    yaml_entries = data.get(section) or []
    if not isinstance(yaml_entries, list):
        return [f"yaml section is not a list (got {type(yaml_entries).__name__})"]

    entity_type = ENTITY_TYPE[section]
    name_key = NAME_KEY[section]
    db_entries = kg.list_live(entity_type)

    # 1. Counts (skip recent_events — yaml is capped at 10, db has full history)
    if section != "recent_events" and len(yaml_entries) != len(db_entries):
        findings.append(
            f"count mismatch: yaml={len(yaml_entries)}  db={len(db_entries)}"
        )

    # 2. Name set comparison
    yaml_names = {_norm(e.get(name_key)) for e in yaml_entries if isinstance(e, dict)}
    yaml_names.discard("")
    db_names = {_norm(n["fields"].get(name_key)) for n in db_entries}
    db_names.discard("")

    in_yaml_not_db = yaml_names - db_names
    in_db_not_yaml = db_names - yaml_names
    for n in sorted(in_yaml_not_db):
        findings.append(f"in yaml but not in db: {n!r}")
    for n in sorted(in_db_not_yaml):
        findings.append(f"in db but not in yaml (sync gap): {n!r}")

    # 3. Field divergence — only for Person (most field-rich)
    if section == "people":
        for ye in yaml_entries:
            if not isinstance(ye, dict):
                continue
            yname = _norm(ye.get("name"))
            if not yname:
                continue
            db_match = next(
                (n for n in db_entries if _norm(n["fields"].get("name")) == yname),
                None,
            )
            if db_match is None:
                continue
            for field in ("kind", "role"):
                ydf = ye.get(field)
                ddf = db_match["fields"].get(field)
                if ydf and ddf and ydf != ddf:
                    findings.append(
                        f"person {yname!r} field '{field}' differs: yaml={ydf!r} db={ddf!r}"
                    )

    return findings


def _norm(s) -> str:
    return (str(s) if s is not None else "").strip().lower()


if __name__ == "__main__":
    sys.exit(main())
