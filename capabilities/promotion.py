"""Promotion gates — when does a staged entity move to live?

Returns (auto_eligible, blocked_reason) for each candidate.
auto_eligible = True  → CARTOGRAPHER promotes immediately.
auto_eligible = False → stays in staging, manual triage via TUI Pending screen.
"""
from __future__ import annotations

from typing import Any

from capabilities.dedup import is_generic_email


def should_auto_promote(
    entity_type: str,
    fields: dict[str, Any],
    *,
    corroboration_count: int = 1,  # distinct docs seen so far
    company_seeded_names: set[str] | None = None,  # from company-config.yml
    has_resolvable_lead: bool = False,
) -> tuple[bool, str | None]:
    """Per-entity auto-promotion logic."""
    company_seeded_names = company_seeded_names or set()

    if entity_type == "Person":
        email = fields.get("email")
        if email and not is_generic_email(email):
            return True, None
        return False, "awaiting_corroboration"  # no email → needs human

    if entity_type == "Team":
        name = (fields.get("name") or "").lower().strip()
        if name and name in company_seeded_names:
            return True, None
        if corroboration_count >= 3:
            return True, None
        return False, "awaiting_corroboration"

    if entity_type == "Project":
        if has_resolvable_lead and corroboration_count >= 2:
            return True, None
        return False, "awaiting_corroboration"

    if entity_type == "Rule":
        # Strict gate — only promote if content has explicit category marker
        content = (fields.get("content") or fields.get("title") or "").lower()
        if any(k in content for k in ("policy", "must", "shall", "rule", "process")):
            return True, None
        return False, "low_quality"

    if entity_type == "Event":
        # Has both date AND name → auto-promote (events rarely duplicate)
        if fields.get("name") and fields.get("date"):
            return True, None
        return False, "low_quality"

    if entity_type == "Document":
        return True, None  # documents always promote

    return False, "unknown_entity_type"
