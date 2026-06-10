"""LLM extractor — RawDocument → {entities, edges} JSON.

Calls Ollama with format='json' for structured output. Retries once on malformed.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

import config

log = logging.getLogger("hannibal.extractor")

EXTRACTION_PROMPT = """You extract entities for a company knowledge graph. Return ONLY valid JSON, no prose, no markdown fences.

CONTEXT: __SELF_COMPANY__ is the company that owns this knowledge graph. The document was uploaded by them. Use this to decide whether a Person is internal (employee) or external, and whether an Organization is a Client (customer of __SELF_COMPANY__).

__DOC_KIND_HINT__

ENTITY DEFINITIONS (strict — when in doubt, omit):

- person: a named human being. Skip generic references ("the team", "the speaker", "the client").
    - kind: "employee" if person is part of __SELF_COMPANY__ (email @__SELF_DOMAIN__, "our team", listed under internal headers); "external" if they belong to a different org (client contact, vendor, consultant); "unknown" if you cannot tell.
    - external_company: required when kind=external — the org the person belongs to.
- team: a named subdivision INSIDE __SELF_COMPANY__ (e.g., "Engineering", "HR"). Do NOT extract __SELF_COMPANY__ itself as a team. Do NOT extract job titles.
- client: an external organization that __SELF_COMPANY__ does business with as a customer. Look for "client", "customer", "engaged by", "contract with", "purchase order from", or party-of-contract framing. Do NOT extract __SELF_COMPANY__ itself as a client. Do NOT extract suppliers/vendors (those are different).
- project: a named initiative or engagement (e.g., "Project Phoenix", "ACME Implementation", "OpenAI Consulting"). kind="external" if it's work for a client (set client_name to the client), "internal" otherwise. status optional ("In Progress", "Done", "On Hold", "Cancelled").
- rule: an explicit policy, process, or value, typically marked by "policy", "must", "shall", "rule", "process". Skip incidental statements.
- event: a company-level dated occurrence (meeting, launch, signing, all-hands). Skip personal life events. A date alone is not an event.
- edge: relationship between two extracted entities. Valid types:
    - MEMBER_OF (person → team)
    - RUNS (person → team OR person → project) — leadership/ownership
    - WORKS_ON (person → project OR team → project) — assignment
    - OWNED_BY (project → client) — external project to its client
    - BELONGS_TO_CLIENT (external person → client) — person works at this client
    - PARTICIPATED_IN (person → event)
    - AUTHORED (person → rule OR person → document)
    - CHILD_OF (team → parent team OR project → parent project)

OUTPUT RULES:
- Only extract what is EXPLICITLY in the document. NO inference, NO invention.
- EVERY extracted entity MUST include `evidence_quote`: a verbatim phrase (≤120 chars) from the document that supports the extraction. If you cannot quote, omit the entity.
- Use exact names as they appear in the document.
- If no entity of a type exists, return an empty list [].

OUTPUT SCHEMA:
{
  "persons":  [{"name": "...", "email": null, "role": null, "kind": "unknown", "external_company": null, "evidence_quote": "..."}],
  "teams":    [{"name": "...", "evidence_quote": "..."}],
  "clients":  [{"name": "...", "industry": null, "contact_email": null, "evidence_quote": "..."}],
  "projects": [{"name": "...", "kind": "internal", "client_name": null, "status": null, "evidence_quote": "..."}],
  "rules":    [{"title": "...", "category": "policy", "evidence_quote": "..."}],
  "events":   [{"name": "...", "date": null, "evidence_quote": "..."}],
  "edges":    [{"from": "...", "type": "WORKS_ON", "to": "...", "role": null}]
}

DOCUMENT:
---
__DOC_TEXT__
---

JSON:"""


EMPTY_RESULT: dict[str, list] = {
    "persons": [], "teams": [],
    "clients": [], "projects": [],
    "rules": [], "events": [], "edges": [],
}


def summarize(text: str, max_chars: int = 4000) -> str:
    """Return a 1-2 sentence plain-English summary of the document. Never raises."""
    if not text or not text.strip():
        return ""
    if len(text) > max_chars:
        text = text[:max_chars] + "\n[TRUNCATED]"
    import ollama
    prompt = (
        "Summarize the document below in 1-2 plain English sentences. "
        "Focus on WHAT it is and WHO/WHAT it concerns. No fluff. No 'this document'. Just the substance.\n\n"
        f"---\n{text}\n---\n\nSummary:"
    )
    try:
        resp = ollama.generate(
            model=config.MASTER_MODEL,
            prompt=prompt,
            options={"temperature": 0.0, "num_predict": 120},
        )
        return (resp.get("response") or "").strip()
    except Exception as e:
        log.warning("summarize_failed", extra={"error": str(e)})
        return ""


def extract(
    text: str,
    max_chars: int = 8000,
    *,
    doc_kind: str | None = None,
    self_company: str | None = None,
    self_domain: str | None = None,
) -> dict[str, list]:
    """Return validated extraction dict. Always has all keys, never raises.

    `doc_kind` (from SENTINEL pre-pass): hint added to prompt so extractor
    can focus its attention (contract → parties+dates; meeting → people+decisions).
    `self_company` / `self_domain`: identity of the company this KG serves;
    drives Client and Person.kind disambiguation.
    """
    if not text or not text.strip():
        return dict(EMPTY_RESULT)

    if len(text) > max_chars:
        text = text[:max_chars] + "\n[TRUNCATED]"

    raw = _call_llm(text, doc_kind=doc_kind, self_company=self_company, self_domain=self_domain)
    parsed = _parse_json(raw)

    if parsed is None:
        log.warning("extract_retry", extra={"reason": "json_invalid_first_try"})
        raw = _call_llm(
            text, retry=True,
            doc_kind=doc_kind, self_company=self_company, self_domain=self_domain,
        )
        parsed = _parse_json(raw)

    if parsed is None:
        log.error("extract_failed", extra={"raw_preview": raw[:200]})
        return dict(EMPTY_RESULT)

    return _normalize(parsed, source_text=text)


# ---------------------------------------------------------------------------
def _call_llm(
    text: str,
    retry: bool = False,
    *,
    doc_kind: str | None = None,
    self_company: str | None = None,
    self_domain: str | None = None,
) -> str:
    """Ollama call with format=json."""
    import ollama

    company = self_company or (config.COMPANY or {}).get("identity", {}).get("name") or "the company"
    domain = self_domain or (config.COMPANY or {}).get("identity", {}).get("domain") or ""
    kind_hint = (
        f"DOC_KIND: SENTINEL classified this as a `{doc_kind}`. Bias extraction accordingly."
        if doc_kind else ""
    )

    prompt = (
        EXTRACTION_PROMPT
        .replace("__DOC_TEXT__", text)
        .replace("__SELF_COMPANY__", company)
        .replace("__SELF_DOMAIN__", domain or "the-company.com")
        .replace("__DOC_KIND_HINT__", kind_hint)
    )
    if retry:
        prompt += "\n\nIMPORTANT: previous attempt was malformed. Return ONLY valid JSON, no prose."

    response = ollama.generate(
        model=config.MASTER_MODEL,
        prompt=prompt,
        format="json",
        options={"temperature": 0.0},
    )
    return response.get("response", "")


def _parse_json(raw: str) -> dict | None:
    """Parse JSON, attempt recovery from common errors."""
    if not raw:
        return None
    cleaned = raw.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                return None
        return None


def _normalize(parsed: dict, *, source_text: str = "") -> dict[str, list]:
    """Ensure all keys exist as lists. Filter null/empty entries. Drop entities
    whose `evidence_quote` doesn't actually appear in the source text (anti-
    hallucination guard, Phase 10E)."""
    haystack = _normalize_for_match(source_text)
    out: dict[str, list] = {}
    for key in EMPTY_RESULT:
        raw_list = parsed.get(key, [])
        if not isinstance(raw_list, list):
            raw_list = []
        out[key] = [
            item for item in raw_list
            if _is_useful(key, item) and _evidence_present(key, item, haystack)
        ]
    return out


def _is_useful(key: str, item: Any) -> bool:
    if not isinstance(item, dict):
        return False
    if key == "edges":
        return bool(item.get("from") and item.get("to") and item.get("type"))
    if key == "rules":
        return bool(item.get("title"))
    return bool(item.get("name"))


_WS_RE = re.compile(r"\s+")


def _normalize_for_match(text: str) -> str:
    """Lowercase + collapse whitespace for quote-in-source matching."""
    return _WS_RE.sub(" ", (text or "").lower()).strip()


def _evidence_present(key: str, item: dict, haystack: str) -> bool:
    """Edges have no evidence_quote requirement (they reference other entities
    that already carry quotes). Entities must have a non-trivial quote that
    appears in the source text. Short quotes (<6 chars) are rejected as
    insufficient signal."""
    if key == "edges":
        return True
    if not haystack:
        return True  # no source text → skip check (callers like tests may not pass it)
    quote = (item.get("evidence_quote") or "").strip()
    if not quote or len(quote) < 6:
        log.info("extract_dropped_no_quote", extra={"type": key, "item": item.get("name") or item.get("title")})
        return False
    needle = _normalize_for_match(quote)
    if needle in haystack:
        return True
    # Lenient fallback: if first 30 chars match, accept (LLM may paraphrase tail)
    head = needle[:30]
    if len(head) >= 10 and head in haystack:
        return True
    log.info(
        "extract_dropped_quote_not_in_source",
        extra={"type": key, "item": item.get("name") or item.get("title"),
               "quote_preview": quote[:60]},
    )
    return False
