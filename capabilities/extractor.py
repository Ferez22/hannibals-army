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

ENTITY DEFINITIONS (strict — when in doubt, omit):

- person: a named human being. Skip generic references ("the team", "the speaker", "the client").
- team: a named subdivision INSIDE a company (e.g., "Engineering", "HR", "Backend"). Do NOT extract the company itself as a team. Do NOT extract job titles. A team must be an internal organizational unit.
- project: a named initiative or product the company works on (e.g., "Additionality", "Product Alpha"). Do NOT extract todo items, tasks, or to-do list entries as projects. A project has a name that would appear on a roadmap, not on a checklist.
- rule: an explicit policy, process, or value, typically marked by words like "policy", "must", "shall", "rule", "process". Skip incidental statements. If the doc isn't explicitly defining a rule, omit.
- event: a company-level dated occurrence (meeting, launch, signing, all-hands). Do NOT extract personal life events (births, passport issuance, ID card issuance). A date alone is not an event.
- edge: relationship between two extracted entities. Valid types: MEMBER_OF, RUNS, PARTICIPATED_IN, AUTHORED, OWNED_BY, CHILD_OF.

OUTPUT RULES:
- Only extract what is EXPLICITLY in the document text
- Use exact names as they appear in the document
- If no entity of a type exists, return an empty list []
- Do not infer or invent

OUTPUT SCHEMA:
{
  "persons":  [{"name": "...", "email": null, "role": null}],
  "teams":    [{"name": "...", "parent": null}],
  "projects": [{"name": "...", "lead": null, "status": null}],
  "rules":    [{"title": "...", "category": "policy"}],
  "events":   [{"name": "...", "date": null}],
  "edges":    [{"from": "...", "type": "MEMBER_OF", "to": "...", "role": null}]
}

DOCUMENT:
---
__DOC_TEXT__
---

JSON:"""


EMPTY_RESULT: dict[str, list] = {
    "persons": [], "teams": [], "projects": [],
    "rules": [], "events": [], "edges": [],
}


def extract(text: str, max_chars: int = 8000) -> dict[str, list]:
    """Return validated extraction dict. Always has 6 keys, never raises."""
    if not text or not text.strip():
        return dict(EMPTY_RESULT)

    if len(text) > max_chars:
        text = text[:max_chars] + "\n[TRUNCATED]"

    raw = _call_llm(text)
    parsed = _parse_json(raw)

    if parsed is None:
        log.warning("extract_retry", extra={"reason": "json_invalid_first_try"})
        raw = _call_llm(text, retry=True)
        parsed = _parse_json(raw)

    if parsed is None:
        log.error("extract_failed", extra={"raw_preview": raw[:200]})
        return dict(EMPTY_RESULT)

    return _normalize(parsed)


# ---------------------------------------------------------------------------
def _call_llm(text: str, retry: bool = False) -> str:
    """Ollama call with format=json."""
    import ollama

    prompt = EXTRACTION_PROMPT.replace("__DOC_TEXT__", text)
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


def _normalize(parsed: dict) -> dict[str, list]:
    """Ensure all 6 keys exist as lists. Filter null/empty entries."""
    out: dict[str, list] = {}
    for key in EMPTY_RESULT:
        raw_list = parsed.get(key, [])
        if not isinstance(raw_list, list):
            raw_list = []
        out[key] = [item for item in raw_list if _is_useful(key, item)]
    return out


def _is_useful(key: str, item: Any) -> bool:
    if not isinstance(item, dict):
        return False
    if key == "edges":
        return bool(item.get("from") and item.get("to") and item.get("type"))
    if key == "rules":
        return bool(item.get("title"))
    return bool(item.get("name"))
