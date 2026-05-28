"""Mirror live KG state into company-config.yml after writes.

CARTOGRAPHER calls sync_company_config() after each ingestion batch.
Single-writer rule: only CARTOGRAPHER writes content blocks.
"""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

import config
from capabilities import yaml_io
from core.knowledge_graph import KnowledgeGraph

log = logging.getLogger("hannibal.yaml_sync")


CONFIG_PATH = config.REPO_ROOT / "company-config.yml"
RECENT_EVENTS_CAP = 10


def sync_company_config(kg: KnowledgeGraph, written_by: str = "CARTOGRAPHER") -> None:
    """Rebuild people/teams/projects/rules/recent_events blocks from live KG."""
    existing = yaml_io.read_yaml(CONFIG_PATH)
    if not isinstance(existing, dict):
        existing = {}

    existing["_meta"] = {
        "last_updated_by": written_by,
        "last_updated_at": datetime.now().isoformat(),
        "confidence_score": 1.0,
        "schema_version": existing.get("_meta", {}).get("schema_version", "1.0"),
    }

    # Keep identity/leadership/tools/culture sections as-is — those are human-curated
    # We rewrite teams, people, projects, rules, recent_events

    existing["teams"] = _build_teams(kg)
    existing["people"] = _build_people(kg)
    existing["projects"] = _build_projects(kg)
    existing["rules"] = _build_rules(kg)
    existing["recent_events"] = _build_recent_events(kg)

    yaml_io.write_yaml_atomic(CONFIG_PATH, existing)
    log.info("company_config_synced", extra={"by": written_by})


# ---------------------------------------------------------------------------
def _build_teams(kg: KnowledgeGraph) -> list[dict]:
    teams = kg.list_live("Team")
    out: list[dict] = []
    for t in teams:
        f = t["fields"]
        out.append({
            "name":    f.get("name"),
            "lead":    f.get("lead_id"),
            "mission": f.get("mission"),
            "domain":  f.get("domain"),
            "parent":  f.get("parent_team_id"),
            "confidence": t["confidence"],
        })
    return out


def _build_people(kg: KnowledgeGraph) -> list[dict]:
    persons = kg.list_live("Person")
    out: list[dict] = []
    for p in persons:
        f = p["fields"]
        memberships: list[dict] = []
        for edge in kg.neighbors(p["id"]):
            if edge["from_id"] != p["id"] or edge["type"] != "MEMBER_OF":
                continue
            team = kg.get_live(edge["to_id"])
            if not team:
                continue
            memberships.append({
                "team":      team["fields"].get("name"),
                "role":      edge["properties"].get("role"),
                "sub_roles": edge["properties"].get("sub_roles", []) or [],
                "tasks":     edge["properties"].get("tasks", []) or [],
                "since":     edge["properties"].get("since"),
            })
        out.append({
            "name":             f.get("name"),
            "kind":             f.get("kind", "unknown"),
            "emails":           f.get("emails", []) or [],
            "role":             f.get("role"),
            "sub_roles":        f.get("sub_roles", []) or [],
            "external_company": f.get("external_company"),
            "photo_path":       f.get("photo_path"),
            "tenure_since":     f.get("tenure_since"),
            "expertise":        f.get("expertise", []) or [],
            "memberships":      memberships,
            "confidence":       p["confidence"],
        })
    return out


def _build_projects(kg: KnowledgeGraph) -> list[dict]:
    projects = kg.list_live("Project")
    out: list[dict] = []
    for p in projects:
        f = p["fields"]
        out.append({
            "name":    f.get("name"),
            "status":  f.get("status"),
            "lead":    f.get("lead"),
            "team":    f.get("team_id"),
            "started": f.get("started"),
            "target":  f.get("target"),
            "description": f.get("description"),
            "last_updated_at": p["last_verified_at"],
        })
    return out


def _build_rules(kg: KnowledgeGraph) -> list[dict]:
    rules = kg.list_live("Rule")
    out: list[dict] = []
    for r in rules:
        f = r["fields"]
        out.append({
            "id":       r["id"],
            "title":    f.get("title"),
            "category": f.get("category"),
            "content":  f.get("content"),
            "owner":    f.get("owner_id"),
            "notify_person": f.get("notify_person_id"),
            "valid_until":   f.get("valid_until"),
            "confidence_score": r["confidence"],
            "last_verified_at": r["last_verified_at"],
        })
    return out


def _build_recent_events(kg: KnowledgeGraph) -> list[dict]:
    events = kg.list_live("Event")
    # Sort by date desc, cap
    def _key(e: dict) -> str:
        return (e["fields"].get("date") or "") or e["created_at"]
    events_sorted = sorted(events, key=_key, reverse=True)[:RECENT_EVENTS_CAP]
    out: list[dict] = []
    for e in events_sorted:
        f = e["fields"]
        out.append({
            "name":    f.get("name"),
            "date":    f.get("date"),
            "type":    f.get("type"),
            "outcome": f.get("outcome"),
        })
    return out
