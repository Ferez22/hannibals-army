"""Directory import logic — feeds `DirectoryEntry` rows into the live KG.

Phase 11A: bootstraps the Person hierarchy. Existing Persons matched by email
get their tier + title patched in-place; new ones are inserted as live
unconfirmed Persons with `kind='employee'` (anyone in the company directory is,
by definition, internal).

Reporting lines (`manager_email` → manager Person) become MEMBER_OF edges with
`role='direct_report'` properties — the manager is the team-of-one parent. This
is a simple bootstrap; real Team membership still comes from documents +
manual Teams screen.

Confirmation policy: imports are SEMI-AUTHORITATIVE. CEO opted to point the
adapter at this data, so we set `tier_confirmed=True` (no UNCONFIRMED_BANNER for
directory-sourced tier), but `confirmed=False` on the Person itself — the
Audit screen still surfaces them so CEO can verify role / department.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import config
from capabilities.directory_adapter import DirectoryEntry
from core.knowledge_graph import KnowledgeGraph

log = logging.getLogger("hannibal.directory_import")


@dataclass
class ImportResult:
    created: int = 0
    updated: int = 0
    skipped: int = 0
    manager_edges_added: int = 0
    errors: list[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.errors is None:
            self.errors = []


def import_directory(kg: KnowledgeGraph, entries: list[DirectoryEntry]) -> ImportResult:
    """Two-pass: first upsert all Persons (so manager_email can resolve), then
    wire MEMBER_OF reporting edges."""
    result = ImportResult()
    email_to_id: dict[str, str] = {}

    # Pass 1 — upsert each entry as Person.
    for entry in entries:
        try:
            pid = _upsert_person(kg, entry, result)
            if pid:
                email_to_id[entry.email] = pid
        except Exception as e:
            msg = f"{entry.email}: {type(e).__name__}: {e}"
            log.exception("directory_import_row_failed", extra={"email": entry.email})
            result.errors.append(msg)

    # Pass 2 — manager edges.
    for entry in entries:
        if not entry.manager_email:
            continue
        person_id = email_to_id.get(entry.email)
        manager_id = email_to_id.get(entry.manager_email) or _lookup_by_email(kg, entry.manager_email)
        if not person_id or not manager_id or person_id == manager_id:
            continue
        if _has_reports_to_edge(kg, person_id, manager_id):
            continue
        kg.add_live_edge(
            from_id=person_id, type="MEMBER_OF", to_id=manager_id,
            properties={"role": "direct_report", "source": "directory_import"},
        )
        result.manager_edges_added += 1

    log.info("directory_import_done", extra={
        "n_created": result.created, "n_updated": result.updated,
        "n_skipped": result.skipped, "n_manager_edges": result.manager_edges_added,
        "n_errors": len(result.errors),
    })

    # Phase 12 — refresh personas for every touched Person so the bot picks up
    # new titles/tiers immediately. Failures are non-fatal: persona will catch
    # up on next chat or daily DONNA scan.
    try:
        from agents.scribe import SCRIBE
        SCRIBE.kg = kg
        for pid in email_to_id.values():
            SCRIBE.invoke({"action": "build", "person_id": pid})
    except Exception as e:
        log.warning("scribe_post_import_failed", extra={"error": str(e)})

    return result


# ---------------------------------------------------------------------------
def _upsert_person(
    kg: KnowledgeGraph, entry: DirectoryEntry, result: ImportResult,
) -> str | None:
    """Match existing Person by email (case-insensitive). Patch tier + title +
    department if found; otherwise create new live Person."""
    tier = _resolve_tier(entry)

    existing = _lookup_by_email(kg, entry.email)
    if existing:
        existing_node = kg.get_live(existing)
        if not existing_node:
            result.skipped += 1
            return None
        f = existing_node["fields"]
        # Directory is authoritative on title/department/tier. Overwrite when
        # the source provides a value (don't clobber to None if source omits).
        if entry.title and f.get("role") != entry.title:
            kg.update_live_field(existing, "role", entry.title)
        if entry.department and f.get("department") != entry.department:
            kg.update_live_field(existing, "department", entry.department)
        if f.get("kind") != "employee":
            kg.update_live_field(existing, "kind", "employee")
        # Tier: directory is authoritative on import — overwrite + confirm.
        kg.update_live_field(existing, "tier", tier)
        kg.update_live_field(existing, "tier_confirmed", True)
        result.updated += 1
        return existing

    # Create new live Person — bypass staging+pending (matches `kg.promote`
    # semantics but skips the staging round-trip).
    fields = {
        "name": entry.name,
        "kind": "employee",
        "emails": [entry.email],
        "role": entry.title or None,
        "sub_roles": [],
        "external_company": None,
        "department": entry.department or None,
        "tier": tier,
        "tier_confirmed": True,
        "telegram_chat_id": None,
    }
    staging_id = kg.stage_entity(
        entity_type="Person",
        fields=fields,
        doc_id=None,
        promotion_status="auto_eligible",
        blocked_reason="directory_import",
    )
    live_id = kg.promote(staging_id, f"Person directory: {entry.name} <{entry.email}>", confirmed=False)
    # Bump corroboration once so confidence isn't pinned at 0.33 forever.
    kg.bump_corroboration(live_id)
    result.created += 1
    return live_id


def _resolve_tier(entry: DirectoryEntry) -> str:
    """Explicit tier column wins; otherwise apply title rules."""
    if entry.tier_override:
        candidate = entry.tier_override.strip().lower()
        if candidate in config.TIERS:
            return candidate
        log.warning(
            "directory_invalid_tier_override",
            extra={"email": entry.email, "got": entry.tier_override},
        )
    return config.tier_from_title(entry.title)


def _lookup_by_email(kg: KnowledgeGraph, email: str) -> str | None:
    target = email.lower()
    for p in kg.list_live("Person"):
        for e in (p["fields"].get("emails") or []):
            if e.lower() == target:
                return p["id"]
    return None


def _has_reports_to_edge(kg: KnowledgeGraph, person_id: str, manager_id: str) -> bool:
    edges = kg.graph.find_edges(kg.company_id, person_id, "MEMBER_OF", manager_id)
    return any(
        (e.get("properties") or {}).get("role") == "direct_report" for e in edges
    )
