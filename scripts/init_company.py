"""Initialize company-config.yml with real data.

One-shot CLI. Prompts user for identity / leadership / tools / culture and writes
a clean company-config.yml. Preserves agent-mirrored sections (teams, people,
projects, rules, recent_events) if they already exist with non-sample data.

Backs up the existing file to company-config.yml.bak before overwriting.

Usage:
    .venv/bin/python scripts/init_company.py
    .venv/bin/python scripts/init_company.py --non-interactive --name "QartMina" --hq "Tunis"
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from capabilities import yaml_io

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = REPO_ROOT / "company-config.yml"
BACKUP_PATH = REPO_ROOT / "company-config.yml.bak"

SAMPLE_MARKERS = {"Acme Corp", "Jane Doe", "John Smith", "Maria Lopez", "Alice Chen", "Bob Müller"}


def _looks_like_sample(data: dict) -> bool:
    """Heuristic: does the file still have John Doe / Acme Corp data?"""
    identity_name = (data.get("identity") or {}).get("name", "")
    if identity_name in SAMPLE_MARKERS:
        return True
    leadership_names = {
        (data.get("leadership", {}).get("ceo") or {}).get("name", ""),
        (data.get("leadership", {}).get("cto") or {}).get("name", ""),
    }
    return bool(leadership_names & SAMPLE_MARKERS)


def _ask(prompt: str, default: str | None = None) -> str:
    suffix = f" [{default}]" if default else ""
    raw = input(f"{prompt}{suffix}: ").strip()
    return raw or (default or "")


def _ask_list(prompt: str) -> list[str]:
    raw = input(f"{prompt} (comma-separated, blank to skip): ").strip()
    if not raw:
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]


def interactive_prompts() -> dict:
    print("\n=== Hannibal's Army — company-config initializer ===\n")

    # Identity
    print("[ identity ]")
    name = _ask("company name", "QartMina")
    legal_name = _ask("legal name", name)
    industry = _ask("industry", "Software / Consulting")
    founded = _ask("founded (YYYY)")
    size = _ask("size (e.g. 11-50)")
    hq = _ask("HQ address (full)")
    timezone = _ask("timezone", "CET")
    website = _ask("website URL")
    languages = _ask_list("languages")
    email_domain = _ask("email domain (e.g. qartmina.com)")

    # Leadership
    print("\n[ leadership — fill what you know, skip if unknown ]")
    ceo_name = _ask("CEO name")
    ceo_email = _ask("CEO email") if ceo_name else ""
    ceo_contact = _ask("CEO contact (telegram, phone, etc)") if ceo_name else ""
    cto_name = _ask("CTO name (skip if same person as CEO)")
    cto_email = _ask("CTO email") if cto_name else ""
    hr_name = _ask("HR lead name")
    hr_email = _ask("HR lead email") if hr_name else ""

    # Tools
    print("\n[ tools ]")
    productivity = _ask_list("productivity tools (Notion, Slack, etc)")
    development = _ask_list("development tools (GitHub, Docker, Azure, etc)")
    communication = _ask_list("communication tools")
    design = _ask_list("design tools")
    finance = _ask_list("finance tools")

    # Culture
    print("\n[ culture ]")
    values = _ask_list("company values")
    working_style = _ask("working style (e.g. 'async-first, deep work')")
    review_cycle = _ask("review cycle (e.g. 'Quarterly')")
    all_hands_freq = _ask("all-hands frequency (e.g. 'Monthly')")

    return {
        "identity": _drop_empty({
            "name": name,
            "legal_name": legal_name,
            "industry": industry,
            "founded": founded,
            "size": size,
            "hq": hq,
            "timezone": timezone,
            "website": website,
            "languages": languages,
            "email_domain": email_domain,
        }),
        "leadership": _drop_empty({
            "ceo": _drop_empty({"name": ceo_name, "email": ceo_email, "contact": ceo_contact}),
            "cto": _drop_empty({"name": cto_name, "email": cto_email}),
            "hr_lead": _drop_empty({"name": hr_name, "email": hr_email,
                                    "note": "Primary contact for rule/policy validation notifications" if hr_name else ""}),
        }),
        "tools": _drop_empty({
            "productivity": productivity,
            "development": development,
            "communication": communication,
            "design": design,
            "finance": finance,
        }),
        "culture": _drop_empty({
            "values": values,
            "working_style": working_style,
            "review_cycle": review_cycle,
            "all_hands_frequency": all_hands_freq,
        }),
    }


def _drop_empty(d: dict) -> dict:
    """Remove keys whose value is empty string / empty list / empty dict."""
    return {k: v for k, v in d.items() if v not in ("", [], {}, None)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true",
                        help="Overwrite even if current config does not look like sample data")
    parser.add_argument("--non-interactive", action="store_true",
                        help="Skip prompts, only write the minimum from flags")
    parser.add_argument("--name", default="", help="company name (non-interactive)")
    parser.add_argument("--hq", default="", help="HQ address (non-interactive)")
    args = parser.parse_args()

    existing = yaml_io.read_yaml(CONFIG_PATH) if CONFIG_PATH.exists() else {}
    sample = _looks_like_sample(existing)

    if CONFIG_PATH.exists() and not sample and not args.force:
        print(f"company-config.yml already looks like real data (identity.name = "
              f"{existing.get('identity', {}).get('name')!r}).")
        print("Pass --force to overwrite, or edit the file by hand.")
        return 1

    if CONFIG_PATH.exists():
        shutil.copy2(CONFIG_PATH, BACKUP_PATH)
        print(f"backed up → {BACKUP_PATH.relative_to(REPO_ROOT)}")

    # Build new sections
    if args.non_interactive:
        new_sections = {
            "identity": _drop_empty({"name": args.name, "hq": args.hq}),
            "leadership": {},
            "tools": {},
            "culture": {},
        }
    else:
        new_sections = interactive_prompts()

    # Merge: keep agent-mirrored sections from old file ONLY if not sample data
    preserved_keys = ["teams", "people", "projects", "rules", "recent_events", "clients"]
    new_data: dict = {"_meta": {"schema_version": "1.1", "confidence_score": 1.0}}
    new_data.update(new_sections)
    if not sample:
        for k in preserved_keys:
            if k in existing:
                new_data[k] = existing[k]
    else:
        # Sample data → clear mirrored sections too so user starts fresh
        for k in preserved_keys:
            new_data[k] = []

    # Audit entry
    yaml_io.append_edit_history(
        new_data,
        by="init_script",
        action="create" if not CONFIG_PATH.exists() else "reset",
        sections=list(new_sections.keys()),
    )

    yaml_io.write_yaml_atomic(CONFIG_PATH, new_data)
    print(f"\n✔ wrote {CONFIG_PATH.relative_to(REPO_ROOT)}")
    print(f"  identity.name = {new_data.get('identity', {}).get('name', '—')!r}")
    print(f"  identity.hq   = {new_data.get('identity', {}).get('hq', '—')!r}")
    print(f"\nNext: run the TUI ({sys.executable} main.py) and check the new config is loaded.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
