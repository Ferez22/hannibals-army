"""CARTOGRAPHER — extracts entities, dedupes, writes to staging, runs promotion gates."""
from __future__ import annotations

import logging
from typing import Any

import config
from agents.base_agent import AgentResult, BaseAgent
from capabilities import dedup, extractor, promotion
from core.entity_types import RawDocument
from core.knowledge_graph import KnowledgeGraph

log = logging.getLogger("hannibal.cartographer")


# Map extractor output keys → entity type names
_TYPE_MAP = {
    "persons":  "Person",
    "teams":    "Team",
    "projects": "Project",
    "rules":    "Rule",
    "events":   "Event",
}


def _entity_description(entity_type: str, fields: dict[str, Any]) -> str:
    """Compact text representation for vector embedding."""
    if entity_type == "Person":
        parts = [fields.get("name", "")]
        if fields.get("email"):
            parts.append(f"email {fields['email']}")
        if fields.get("role"):
            parts.append(f"role {fields['role']}")
        return ", ".join(p for p in parts if p)
    if entity_type == "Team":
        return f"Team: {fields.get('name', '')}"
    if entity_type == "Project":
        parts = [f"Project {fields.get('name', '')}"]
        if fields.get("status"):
            parts.append(f"status {fields['status']}")
        if fields.get("lead"):
            parts.append(f"lead {fields['lead']}")
        return ", ".join(p for p in parts if p)
    if entity_type == "Rule":
        return f"Rule {fields.get('title', '')}: {fields.get('content', '')}"
    if entity_type == "Event":
        return f"Event {fields.get('name', '')} on {fields.get('date', 'unknown date')}"
    return str(fields.get("name", ""))


def _seeded_team_names() -> set[str]:
    """Team names already declared in company-config.yml — they auto-promote."""
    teams = (config.COMPANY or {}).get("teams", []) or []
    names: set[str] = set()
    for t in teams:
        if isinstance(t, dict) and t.get("name"):
            names.add(t["name"].lower().strip())
        for sub in (t.get("sub_teams") or []) if isinstance(t, dict) else []:
            if isinstance(sub, dict) and sub.get("name"):
                names.add(sub["name"].lower().strip())
    return names


class Cartographer(BaseAgent):
    name = "CARTOGRAPHER"
    tagline = "knowledge writer — extracts entities into staging"
    persona = "Cartographer maps the territory."

    def __init__(self, kg: KnowledgeGraph | None = None) -> None:
        super().__init__(kg=kg)

    def invoke(self, task: dict[str, Any]) -> AgentResult:
        """task: {"raw_doc": RawDocument, "doc_node_id": <live Document id>}"""
        raw_doc: RawDocument | None = task.get("raw_doc")
        doc_node_id: str | None = task.get("doc_node_id")
        if not raw_doc:
            return AgentResult(False, error="missing 'raw_doc'")
        if self.kg is None:
            return AgentResult(False, error="cartographer has no KG bound")

        log.info(
            "cartographer_start",
            extra={"source": raw_doc.source, "chars": len(raw_doc.raw_text)},
        )

        extraction = extractor.extract(raw_doc.raw_text)
        log.info(
            "extraction_done",
            extra={k: len(v) for k, v in extraction.items()},
        )

        # Promote each entity type
        seeded_teams = _seeded_team_names()
        promoted_ids: dict[str, list[str]] = {k: [] for k in _TYPE_MAP.values()}
        staged_ids: dict[str, list[str]] = {k: [] for k in _TYPE_MAP.values()}
        bumped_ids: list[str] = []  # existing live OR pending nodes corroborated

        # Snapshot pending stagings once — used to dedup new extractions
        existing_pending = self.kg.list_pending()

        for ext_key, entity_type in _TYPE_MAP.items():
            existing_live = self.kg.list_live(entity_type)
            pending_for_type = [p for p in existing_pending if p["entity_type"] == entity_type]

            for item in extraction.get(ext_key, []):
                # 1) Dedup against LIVE
                existing_id = dedup.find_existing(entity_type, item, existing_live)
                if existing_id:
                    self.kg.bump_corroboration(existing_id)
                    bumped_ids.append(existing_id)
                    log.info(
                        "corroborated_live",
                        extra={"entity_type": entity_type, "live_id": existing_id},
                    )
                    continue

                # 2) Dedup against PENDING staging (avoid creating duplicate staged rows)
                pending_match = dedup.find_existing(entity_type, item, pending_for_type)
                if pending_match:
                    log.info(
                        "skipped_duplicate_pending",
                        extra={"entity_type": entity_type, "staging_id": pending_match},
                    )
                    continue

                # 3) New — apply promotion gate
                fields = _to_storage_fields(entity_type, item)
                auto, reason = promotion.should_auto_promote(
                    entity_type,
                    fields,
                    company_seeded_names=seeded_teams,
                )

                if auto:
                    staging_id = self.kg.stage_entity(
                        entity_type=entity_type,
                        fields=fields,
                        doc_id=doc_node_id,
                        promotion_status="auto_eligible",
                    )
                    live_id = self.kg.promote(staging_id, _entity_description(entity_type, fields))
                    promoted_ids[entity_type].append(live_id)
                    # Add to live list so subsequent items in same batch dedup against it
                    existing_live.append(self.kg.get_live(live_id))
                    log.info(
                        "auto_promoted",
                        extra={"entity_type": entity_type, "live_id": live_id},
                    )
                else:
                    staging_id = self.kg.stage_entity(
                        entity_type=entity_type,
                        fields=fields,
                        doc_id=doc_node_id,
                        promotion_status="pending",
                        blocked_reason=reason,
                    )
                    staged_ids[entity_type].append(staging_id)
                    # Add to pending list so subsequent items in same batch dedup against it
                    pending_for_type.append({
                        "id": staging_id,
                        "entity_type": entity_type,
                        "fields": fields,
                    })
                    log.info(
                        "staged_pending",
                        extra={"entity_type": entity_type, "reason": reason},
                    )

        # Edges — only between promoted/existing live nodes
        edges_added = 0
        for edge in extraction.get("edges", []):
            from_id = _resolve_node_by_name(self.kg, edge.get("from"))
            to_id = _resolve_node_by_name(self.kg, edge.get("to"))
            if from_id and to_id:
                props = {}
                if edge.get("role"):
                    props["role"] = edge["role"]
                self.kg.add_live_edge(
                    from_id=from_id, type=edge["type"], to_id=to_id, properties=props
                )
                edges_added += 1

        return AgentResult(
            True,
            data={
                "promoted": {k: len(v) for k, v in promoted_ids.items()},
                "staged":   {k: len(v) for k, v in staged_ids.items()},
                "corroborated": len(bumped_ids),
                "edges_added": edges_added,
                "raw_extraction": extraction,
            },
        )


# ---------------------------------------------------------------------------
def _to_storage_fields(entity_type: str, item: dict[str, Any]) -> dict[str, Any]:
    """Normalize extractor output into storage-shaped fields."""
    if entity_type == "Person":
        return {
            "name": item.get("name", "").strip(),
            "email": (item.get("email") or "").strip() or None,
            "role": (item.get("role") or "").strip() or None,
        }
    if entity_type == "Team":
        return {
            "name": item.get("name", "").strip(),
            "parent_team_id": (item.get("parent") or "").strip() or None,
        }
    if entity_type == "Project":
        return {
            "name": item.get("name", "").strip(),
            "lead": (item.get("lead") or "").strip() or None,
            "status": (item.get("status") or "").strip() or None,
        }
    if entity_type == "Rule":
        return {
            "title": item.get("title", "").strip(),
            "content": item.get("content", item.get("title", "")).strip(),
            "category": item.get("category", "policy"),
        }
    if entity_type == "Event":
        return {
            "name": item.get("name", "").strip(),
            "date": (item.get("date") or "").strip() or None,
        }
    return dict(item)


def _resolve_node_by_name(kg: KnowledgeGraph, name: str | None) -> str | None:
    """Find live node id by name match across all types. Used for edges."""
    if not name:
        return None
    name_tokens = dedup.normalize_tokens(name)
    for node in kg.list_live():
        node_name = node["fields"].get("name") or node["fields"].get("title")
        if dedup.tokens_match(name_tokens, dedup.normalize_tokens(node_name)):
            return node["id"]
    return None


CARTOGRAPHER = Cartographer()
