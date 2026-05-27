"""Deduplication — find existing live nodes that match an extracted entity.

Strategy per entity type:
  Person  → email match (strict) OR name token-set match
  Team    → name + parent
  Project → name + team
  Rule    → title fuzzy match
  Event   → name + date
  Document→ raw_path

Returns existing live_node_id or None.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any

from rapidfuzz import fuzz


# ---------------------------------------------------------------------------
def normalize_tokens(s: str | None) -> frozenset[str]:
    """Order-insensitive name normalization.

    'Ali Khribi' == 'KHRIBI ALI' == 'Smith, John' (for 'John Smith')
    """
    if not s:
        return frozenset()
    s = unicodedata.normalize("NFKD", s)
    s = s.encode("ascii", "ignore").decode("ascii").lower()
    s = re.sub(r"\b(dr|mr|mrs|ms|prof|jr|sr|phd|md)\.?\b", "", s)
    s = re.sub(r"[^\w\s]", " ", s)
    return frozenset(t for t in s.split() if len(t) > 1)


def tokens_match(a: frozenset[str], b: frozenset[str]) -> bool:
    if not a or not b:
        return False
    overlap = a & b
    return len(overlap) >= min(len(a), len(b))


def normalize_domain(email: str | None) -> str:
    if not email or "@" not in email:
        return ""
    return email.split("@", 1)[1].lower().strip()


def is_generic_email(email: str | None) -> bool:
    """Filter noreply@, info@, contact@ etc."""
    if not email or "@" not in email:
        return True
    local = email.split("@", 1)[0].lower()
    return local in {"noreply", "no-reply", "info", "contact", "support", "admin", "hello"}


# ---------------------------------------------------------------------------
def find_existing_person(extracted: dict[str, Any], live_persons: list[dict]) -> str | None:
    ext_email = (extracted.get("email") or "").lower().strip() or None
    ext_tokens = normalize_tokens(extracted.get("name"))

    # Strict: email match
    if ext_email and not is_generic_email(ext_email):
        for p in live_persons:
            if (p["fields"].get("email") or "").lower().strip() == ext_email:
                return p["id"]

    # Fallback: token-set match on name
    for p in live_persons:
        if tokens_match(ext_tokens, normalize_tokens(p["fields"].get("name"))):
            return p["id"]

    return None


def find_existing_team(extracted: dict[str, Any], live_teams: list[dict]) -> str | None:
    name_tokens = normalize_tokens(extracted.get("name"))
    ext_parent = (extracted.get("parent") or "").lower().strip()
    for t in live_teams:
        if tokens_match(name_tokens, normalize_tokens(t["fields"].get("name"))):
            t_parent = (t["fields"].get("parent_team_id") or "").lower().strip()
            if ext_parent == t_parent:
                return t["id"]
    return None


def find_existing_project(extracted: dict[str, Any], live_projects: list[dict]) -> str | None:
    name_tokens = normalize_tokens(extracted.get("name"))
    for p in live_projects:
        if tokens_match(name_tokens, normalize_tokens(p["fields"].get("name"))):
            return p["id"]
    return None


def find_existing_rule(extracted: dict[str, Any], live_rules: list[dict]) -> str | None:
    ext_title = extracted.get("title", "")
    for r in live_rules:
        if fuzz.token_set_ratio(ext_title, r["fields"].get("title", "")) >= 90:
            return r["id"]
    return None


def find_existing_event(extracted: dict[str, Any], live_events: list[dict]) -> str | None:
    name_tokens = normalize_tokens(extracted.get("name"))
    ext_date = (extracted.get("date") or "").strip()
    for e in live_events:
        # Date match alone is strong signal (events with same date likely same)
        if ext_date and e["fields"].get("date") == ext_date:
            return e["id"]
        if tokens_match(name_tokens, normalize_tokens(e["fields"].get("name"))):
            return e["id"]
    return None


# Dispatcher
FINDERS = {
    "Person": find_existing_person,
    "Team": find_existing_team,
    "Project": find_existing_project,
    "Rule": find_existing_rule,
    "Event": find_existing_event,
}


def find_existing(
    entity_type: str, extracted: dict[str, Any], live_nodes: list[dict]
) -> str | None:
    finder = FINDERS.get(entity_type)
    if not finder:
        return None
    return finder(extracted, live_nodes)
