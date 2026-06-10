"""CARTOGRAPHER — extracts entities, dedupes, writes to staging, runs promotion gates."""
from __future__ import annotations

import logging
from typing import Any

import config
from agents.base_agent import AgentResult, BaseAgent
from agents.donna import detect_conflict
from capabilities import dedup, extractor, promotion, yaml_sync
from core.entity_types import RawDocument
from core.knowledge_graph import KnowledgeGraph

log = logging.getLogger("hannibal.cartographer")


# Map extractor output keys → entity type names.
# Phase 10E: re-enabled Client + Project auto-extraction. Auto-promote +
# `confirmed=False` + ORACLE unconfirmed banner replace the old manual gate.
# Manual creation via Clients/Projects screens still supported (those paths
# call `kg.promote(..., confirmed=True)`).
_TYPE_MAP = {
    "persons":  "Person",
    "teams":    "Team",
    "clients":  "Client",
    "projects": "Project",
    "rules":    "Rule",
    "events":   "Event",
}


def _entity_description(entity_type: str, fields: dict[str, Any]) -> str:
    """Compact text representation for vector embedding."""
    if entity_type == "Person":
        parts = [fields.get("name", "")]
        if fields.get("kind"):
            parts.append(fields["kind"])
        if fields.get("external_company"):
            parts.append(f"at {fields['external_company']}")
        emails = fields.get("emails") or []
        if emails:
            parts.append(f"email {emails[0]}")
        if fields.get("role"):
            parts.append(f"role {fields['role']}")
        if fields.get("sub_roles"):
            parts.append("also " + ", ".join(fields["sub_roles"]))
        return ", ".join(p for p in parts if p)
    if entity_type == "Team":
        parts = [f"Team {fields.get('name', '')}"]
        kind = fields.get("kind", "internal")
        parts.append(kind)
        if fields.get("external_org"):
            parts.append(f"at {fields['external_org']}")
        if fields.get("domain"):
            parts.append(f"domain {fields['domain']}")
        return ", ".join(p for p in parts if p)
    if entity_type == "Project":
        parts = [f"Project {fields.get('name', '')}"]
        kind = fields.get("kind", "internal")
        parts.append(kind)
        if fields.get("status"):
            parts.append(f"status {fields['status']}")
        if fields.get("lead"):
            parts.append(f"lead {fields['lead']}")
        if fields.get("client_id"):
            parts.append(f"client_id {fields['client_id']}")
        return ", ".join(p for p in parts if p)
    if entity_type == "Client":
        parts = [f"Client {fields.get('name', '')}"]
        if fields.get("industry"):
            parts.append(f"industry {fields['industry']}")
        if fields.get("domicile"):
            parts.append(f"domicile {fields['domicile']}")
        if fields.get("status"):
            parts.append(f"status {fields['status']}")
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
        """task: {"raw_doc": RawDocument, "doc_node_id": <live Document id>,
                  "doc_kind": <SENTINEL's classification, optional>}"""
        raw_doc: RawDocument | None = task.get("raw_doc")
        doc_node_id: str | None = task.get("doc_node_id")
        doc_kind: str | None = task.get("doc_kind")
        if not raw_doc:
            return AgentResult(False, error="missing 'raw_doc'")
        if self.kg is None:
            return AgentResult(False, error="cartographer has no KG bound")

        log.info(
            "cartographer_start",
            extra={"source": raw_doc.source, "chars": len(raw_doc.raw_text),
                   "doc_kind": doc_kind},
        )

        # Self-company + domain feed the extractor's Client/Person.kind heuristics
        company_cfg = (config.COMPANY or {}).get("identity", {}) or {}
        self_company = company_cfg.get("name")
        self_domain = company_cfg.get("domain") or company_cfg.get("website")
        extraction = extractor.extract(
            raw_doc.raw_text,
            doc_kind=doc_kind,
            self_company=self_company,
            self_domain=self_domain,
        )
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
                    live_node = next((n for n in existing_live if n["id"] == existing_id), None)
                    candidate_fields = _to_storage_fields(entity_type, item)

                    # Auto-merge new emails into existing Person (not a conflict)
                    if entity_type == "Person" and live_node:
                        live_emails = set(live_node["fields"].get("emails") or [])
                        new_emails = set(candidate_fields.get("emails") or [])
                        added_emails = new_emails - live_emails
                        if added_emails:
                            merged = list(live_emails | new_emails)
                            self.kg.update_live_field(existing_id, "emails", merged)
                            log.info(
                                "emails_auto_merged",
                                extra={"live_id": existing_id, "added": list(added_emails)},
                            )

                    # Conflict check before bumping
                    conflict = detect_conflict(entity_type, candidate_fields, live_node) if live_node else None
                    if conflict:
                        # Tag as role_conflict when only role differs — Review screen offers
                        # "Add as sub-role" / "Replace" / "Dismiss" actions
                        review_kind = "role_conflict" if (
                            entity_type == "Person"
                            and set(conflict["diffs"].keys()) == {"role"}
                        ) else "conflict"
                        self.kg.graph.queue_for_review(
                            company_id=self.kg.company_id,
                            kind=review_kind,
                            entity_type=entity_type,
                            live_node_id=existing_id,
                            candidate_node_id=None,
                            details={
                                "doc_id": doc_node_id,
                                "candidate_fields": candidate_fields,
                                "live_fields": live_node["fields"],
                                "diffs": conflict["diffs"],
                            },
                        )
                        log.info(
                            "conflict_queued",
                            extra={"entity_type": entity_type, "live_id": existing_id},
                        )
                        # Still bump corroboration since the entity IS the same identity, only some fields differ
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

                # 3) New — auto-promote unconfirmed (Phase 10D).
                # Gate removed: ORACLE warns on unconfirmed; CEO can confirm/reject
                # in Audit screen. The old `promotion.should_auto_promote` is kept
                # as `blocked_reason` metadata for audit triage but no longer blocks
                # promotion.
                fields = _to_storage_fields(entity_type, item)
                _, gate_reason = promotion.should_auto_promote(
                    entity_type,
                    fields,
                    company_seeded_names=seeded_teams,
                )
                if gate_reason:
                    fields["audit_hint"] = gate_reason
                staging_id = self.kg.stage_entity(
                    entity_type=entity_type,
                    fields=fields,
                    doc_id=doc_node_id,
                    promotion_status="auto_eligible",
                    blocked_reason=gate_reason,
                )
                live_id = self.kg.promote(
                    staging_id,
                    _entity_description(entity_type, fields),
                    confirmed=False,
                )
                promoted_ids[entity_type].append(live_id)
                existing_live.append(self.kg.get_live(live_id))
                log.info(
                    "auto_promoted_unconfirmed",
                    extra={"entity_type": entity_type, "live_id": live_id,
                           "audit_hint": gate_reason},
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
                # Edge ↔ field sync (design decision #8)
                _sync_edge_to_fields(self.kg, edge["type"], from_id, to_id)

        # Fallback: Project.client_name_hint → OWNED_BY edge if LLM forgot to emit it
        for project_id in promoted_ids.get("Project", []):
            proj = self.kg.get_live(project_id)
            if not proj:
                continue
            hint = (proj["fields"].get("client_name_hint") or "").strip()
            if not hint or proj["fields"].get("client_id"):
                continue
            client_id = _resolve_node_by_name(self.kg, hint, entity_type="Client")
            if not client_id:
                continue
            # Check OWNED_BY edge doesn't already exist
            existing = self.kg.graph.find_edges(self.kg.company_id, project_id, "OWNED_BY", client_id)
            if existing:
                continue
            self.kg.add_live_edge(
                from_id=project_id, type="OWNED_BY", to_id=client_id, properties=None
            )
            edges_added += 1
            _sync_edge_to_fields(self.kg, "OWNED_BY", project_id, client_id)
            log.info("owned_by_backfilled_from_hint",
                     extra={"project_id": project_id, "client_id": client_id, "hint": hint})

        # Sync YAML mirror if anything changed
        any_change = (
            any(promoted_ids.values())
            or any(staged_ids.values())
            or bumped_ids
            or edges_added
        )
        if any_change:
            try:
                yaml_sync.sync_company_config(self.kg)
            except Exception as e:
                log.warning("yaml_sync_failed", extra={"error": str(e)})

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
        email = (item.get("email") or "").strip()
        emails = [e.strip() for e in (item.get("emails") or []) if isinstance(e, str) and e.strip()]
        if email and email not in emails:
            emails.append(email)
        kind_raw = (item.get("kind") or "unknown").strip().lower()
        kind = kind_raw if kind_raw in ("employee", "external", "unknown") else "unknown"
        external_company = (item.get("external_company") or "").strip() or None
        # External w/o company → downgrade to unknown so Audit screen prompts for it
        if kind == "external" and not external_company:
            kind = "unknown"
        return {
            "name": item.get("name", "").strip(),
            "kind": kind,
            "emails": emails,
            "role": (item.get("role") or "").strip() or None,
            "sub_roles": [],
            "external_company": external_company,
            "photo_path": None,
        }
    if entity_type == "Team":
        kind_raw = (item.get("kind") or "internal").strip().lower()
        kind = kind_raw if kind_raw in ("internal", "external") else "internal"
        return {
            "name": item.get("name", "").strip(),
            "kind": kind,
            "external_org": (item.get("external_org") or "").strip() or None,
            "parent_team_id": (item.get("parent") or "").strip() or None,
        }
    if entity_type == "Project":
        kind_raw = (item.get("kind") or "internal").strip().lower()
        kind = kind_raw if kind_raw in ("internal", "external") else "internal"
        # client_name from extractor — resolved to client_id in edge pass (OWNED_BY).
        # Stored on fields for Audit screen visibility; promoted edges set the canonical client_id.
        return {
            "name": item.get("name", "").strip(),
            "kind": kind,
            "lead": (item.get("lead") or "").strip() or None,
            "status": (item.get("status") or "").strip() or None,
            "client_id": (item.get("client_id") or "").strip() or None,
            "client_name_hint": (item.get("client_name") or "").strip() or None,
        }
    if entity_type == "Client":
        return {
            "name": item.get("name", "").strip(),
            "industry": (item.get("industry") or "").strip() or None,
            "contact_email": (item.get("contact_email") or "").strip() or None,
            "domicile": (item.get("domicile") or "").strip() or None,
            "status": (item.get("status") or "active").strip() or "active",
            "notes": (item.get("notes") or "").strip() or None,
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


def _sync_edge_to_fields(
    kg: KnowledgeGraph, edge_type: str, from_id: str, to_id: str,
) -> None:
    """Mirror certain edges back into entity fields so downstream readers
    (Clients screen, yaml_sync, ORACLE) work without traversing edges.

    Matches the pattern in `tui/screens/edges.py:create_edge` for manual
    creation. See CLAUDE.md design decision #8.
    """
    if edge_type == "OWNED_BY":
        # Project → Client: set Project.client_id + flip kind to external
        project = kg.get_live(from_id)
        client = kg.get_live(to_id)
        if not project or not client:
            return
        if project["entity_type"] != "Project" or client["entity_type"] != "Client":
            return
        kg.update_live_field(from_id, "client_id", to_id)
        if project["fields"].get("kind") != "external":
            kg.update_live_field(from_id, "kind", "external")
    elif edge_type == "BELONGS_TO_CLIENT":
        # External Person → Client: set Person.external_company to client.name
        person = kg.get_live(from_id)
        client = kg.get_live(to_id)
        if not person or not client:
            return
        if person["entity_type"] != "Person" or client["entity_type"] != "Client":
            return
        client_name = client["fields"].get("name")
        if client_name and person["fields"].get("external_company") != client_name:
            kg.update_live_field(from_id, "external_company", client_name)
            if person["fields"].get("kind") != "external":
                kg.update_live_field(from_id, "kind", "external")


def _resolve_node_by_name(
    kg: KnowledgeGraph, name: str | None, entity_type: str | None = None,
) -> str | None:
    """Find live node id by name match. Used for edges. Optional entity_type
    narrows the search (e.g. resolve to Client only for OWNED_BY targets)."""
    if not name:
        return None
    name_tokens = dedup.normalize_tokens(name)
    for node in kg.list_live(entity_type):
        node_name = node["fields"].get("name") or node["fields"].get("title")
        if dedup.tokens_match(name_tokens, dedup.normalize_tokens(node_name)):
            return node["id"]
    return None


CARTOGRAPHER = Cartographer()
