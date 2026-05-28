"""Debug helper — age live nodes by N days for testing staleness behavior.

Usage:
    .venv/bin/python scripts/age_nodes.py --type Person --days 400
    .venv/bin/python scripts/age_nodes.py --type Rule   --days 200
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from capabilities.graph_store import GraphStore


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--type", required=True, help="entity type (Person, Rule, Team, Project)")
    p.add_argument("--days", type=int, required=True, help="days to age backward")
    p.add_argument("--all", action="store_true", help="age ALL nodes of this type (default: 1)")
    args = p.parse_args()

    aged_at = (datetime.now() - timedelta(days=args.days)).isoformat()
    gs = GraphStore(config.DB_PATH)

    with gs.conn() as c:
        rows = c.execute(
            "SELECT id FROM live_nodes WHERE company_id = ? AND entity_type = ?",
            (config.COMPANY_ID, args.type),
        ).fetchall()
        if not rows:
            print(f"no {args.type} nodes found")
            return 1

        target_ids = [r["id"] for r in rows] if args.all else [rows[0]["id"]]
        for nid in target_ids:
            c.execute(
                "UPDATE live_nodes SET last_verified_at = ? WHERE id = ?",
                (aged_at, nid),
            )
            print(f"aged {nid} → last_verified_at = {aged_at[:10]}")

    print(f"\ndone. {len(target_ids)} {args.type} node(s) aged by {args.days} days.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
