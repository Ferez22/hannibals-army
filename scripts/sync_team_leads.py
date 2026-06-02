"""Backfill Team.lead_id from existing MEMBER_OF edges where role contains "lead".

One-shot fixer. Run once after upgrading to the version that auto-syncs lead.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.knowledge_graph import KnowledgeGraph


def main() -> int:
    kg = KnowledgeGraph()
    kg.init()
    teams = kg.list_live("Team")
    updated = 0
    for t in teams:
        if t["fields"].get("lead_id"):
            continue  # already set
        # Look for any MEMBER_OF edge → this team with role containing lead/head/manager
        for edge in kg.graph.edges_to(kg.company_id, t["id"]):
            if edge["type"] != "MEMBER_OF":
                continue
            role = (edge["properties"].get("role") or "").lower()
            if not any(k in role for k in ("lead", "head", "manager")):
                continue
            person = kg.get_live(edge["from_id"])
            if not person:
                continue
            kg.update_live_field(t["id"], "lead_id", person["id"])
            print(
                f"  {t['fields'].get('name')!r} → lead = {person['fields'].get('name')!r} "
                f"({person['id']}) via role={role!r}"
            )
            updated += 1
            break  # one lead per team
    print(f"\nupdated {updated} team(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
