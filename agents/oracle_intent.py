"""ORACLE intent classifier.

Two-pass:
  1. Lexical fast-path for obvious cases (regex on common patterns).
  2. LLM fallback for everything else, returning strict JSON.

Output: dict {intent, entities_referenced, needs_clarification, clarification_q, suggestions}.
"""
from __future__ import annotations

import logging
import re
from typing import Any

import config
from capabilities import llm

log = logging.getLogger("hannibal.oracle.intent")

# Valid intents in priority order.
VALID_INTENTS = (
    "company",       # self-company questions (HQ, identity, leadership)
    "person", "team", "project", "client",
    "rule", "event", "document",
    "culture",       # values / working style — overlaps with company
    "config_edit",   # CEO instructs an edit to company-config.yml (Telegram only)
    "summary", "unclear",
)


# ---------------------------------------------------------------------------
# Self-company helpers
# ---------------------------------------------------------------------------
def _self_company_aliases() -> set[str]:
    """Tokens that refer to the self-company (QartMina) — lowercase."""
    aliases: set[str] = {"the company", "our company", "us", "we", "this company"}
    identity = (config.COMPANY or {}).get("identity") or {}
    name = (identity.get("name") or config.COMPANY_ID or "").strip().lower()
    legal = (identity.get("legal_name") or "").strip().lower()
    if name:
        aliases.add(name)
    if legal:
        aliases.add(legal)
    return {a for a in aliases if a}


def is_self_company_reference(question: str) -> bool:
    """Does the question reference the self-company?"""
    q = question.lower()
    for alias in _self_company_aliases():
        # word boundary match for short tokens, contains for multi-word phrases
        if " " in alias:
            if alias in q:
                return True
        else:
            if re.search(rf"\b{re.escape(alias)}\b", q):
                return True
    return False


# ---------------------------------------------------------------------------
# Lexical fast-path
# ---------------------------------------------------------------------------
# Patterns ordered by priority — first match wins.
_LEXICAL_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    # CEO config edit — must come first so "remember our HQ is X" routes correctly
    ("config_edit", re.compile(
        r"^(remember|update|set|change|fix|note that|our (hq|address|legal name|industry) is)\b",
        re.I,
    )),
    # Client first — beats `who is` person pattern on "who is our client X"
    ("client", re.compile(
        r"^(list )?(our )?clients?\b|\bwho is our client\b|\bour customer\b", re.I,
    )),
    # Rule — beats culture and company on "how do we handle X" patterns
    ("rule", re.compile(
        r"\b(policy|policies|our rule|how do we handle|whistleblow|harassment|leave policy|holiday|onboarding|offboarding|process for|how to handle)\b",
        re.I,
    )),
    # Self-company / domicile / identity questions + leadership-by-title
    # (only CEO/CTO/CFO/COO/founder — these are STRICTLY identity. Functional
    # leads like "head of engineering" route to TEAM because team.lead_id traversal
    # is the more authoritative source.)
    ("company", re.compile(
        r"\b(hq|head ?quarter|domicil|address|located|registered|legal name|founded|industry of (us|the company)|company website|company about)\b"
        r"|\bwho is (the|our) (ceo|cto|cfo|coo|founder)\b",
        re.I,
    )),
    # Culture / values
    ("culture", re.compile(
        r"\b(values?|culture|working style|mission statement|vision|how (do|does) the company)\b", re.I,
    )),
    # Team — anything about who leads / runs a named team, members, scope, listings.
    # Pattern BEFORE person because "who leads engineering" should be team, not person.
    ("team", re.compile(
        r"\b(who leads|who runs|who heads|head of) (the |our )?(engineering|hr|finance|marketing|sales|operations|ops|product|design|backend|frontend|legal|infra|devops|it|data|research|support|customer success|cs)\b"
        r"|\b(members of|team of|who is in) (the |our )?(engineering|hr|finance|marketing|sales|operations|ops|product|design|backend|frontend|legal|infra|devops|it|data|research|support|customer success|cs)\b"
        r"|\bwhat does (the |our )?(engineering|hr|finance|marketing|sales|operations|ops|product|design|backend|frontend|legal|infra|devops|it|data|research|support|customer success|cs) (team )?do\b"
        r"|\b(which|what|list|all) teams?\b",
        re.I,
    )),
    # Person
    ("person", re.compile(
        r"^(who is|who's|who works on|who leads|who runs|contact for|email of)\b", re.I,
    )),
    # Project — specific + listing variants
    ("project", re.compile(
        r"\b(status of|lead of|who runs project|project status|progress on|deadline of)\b"
        r"|\b(which|what|list|all|ongoing|active|current|open) projects?\b"
        r"|\bprojects?\b.*\b(ongoing|active|current|in progress)\b",
        re.I,
    )),
    # Event
    ("event", re.compile(
        r"\b(when (was|is|did)|what happened|all.?hands|launch date|signed on)\b", re.I,
    )),
    # Document
    ("document", re.compile(
        r"\b(what does the .* (say|state|mention)|in the document|in the contract|per the agreement|the handbook says)\b",
        re.I,
    )),
    # Summary / overview — note `tell me about X` where X is a specific named
    # entity is handled at the upgrade stage (see below).
    ("summary", re.compile(
        r"^(overview|summarize|describe (the company|us)|give me a summary)\b|tell me everything\b",
        re.I,
    )),
    # Generic "tell me about <name>" — usually about a specific entity.
    # Default to summary; will be upgraded to person/team/project/client if
    # the named entity resolves at retrieval time. Keep as summary for now —
    # summary inventory includes every entity so the LLM can answer.
    ("summary", re.compile(r"^tell me about\b", re.I)),
    # Unclear / vague
    ("unclear", re.compile(
        r"^(what'?s? important|anything new|help me|what should i|recap|give me everything)\b", re.I,
    )),
]


def lexical_classify(question: str) -> str | None:
    """Return intent string if a lexical pattern matches, else None.

    Order:
      1. Pattern matches in priority order (rule/person/event/etc beat company override).
      2. Self-company UPGRADE — only fires for client/summary intents that mention
         the self-company. Keeps "how do we handle X" → rule, "what does our policy say" → rule.
    """
    # Step 1: regular pattern match
    matched: str | None = None
    for intent, pat in _LEXICAL_PATTERNS:
        if pat.search(question):
            matched = intent
            break

    # Step 2: self-company upgrade.
    # If the question mentions the self-company AND the matched intent is one that
    # could be mistakenly routed (client, summary, or no match), promote to `company`.
    if is_self_company_reference(question):
        if matched in (None, "client", "summary"):
            return "company"

    return matched


# ---------------------------------------------------------------------------
# LLM fallback
# ---------------------------------------------------------------------------
_INTENT_PROMPT = """Classify the user's question about a company knowledge graph.

Intents (pick exactly one):
- company   : about THE company itself (HQ, address, legal info, leadership, identity)
- person    : about a specific named person
- team      : about a specific team / org subdivision
- project   : about a specific project / engagement / initiative
- client    : about a paying customer organization
- rule      : about a policy, HR rule, process, value (e.g. whistleblowing, onboarding)
- event     : about a dated occurrence (meeting, launch, signing)
- document  : about the content of a specific document/contract/handbook
- culture   : about values, working style, culture
- summary   : broad "tell me about X" / overview / list everything
- unclear   : vague, ambiguous, no clear target — needs clarification

Return ONLY valid JSON:
{
  "intent": "<one of the above>",
  "entities_referenced": [<names mentioned in the question, exact strings>],
  "needs_clarification": <true|false>,
  "clarification_q": "<short follow-up question if needs_clarification, else null>",
  "suggestions": [<3-4 suggested follow-ups if needs_clarification, else []>]
}

QUESTION: __QUESTION__

JSON:"""


def llm_classify(question: str) -> dict[str, Any] | None:
    raw = llm.generate(model=config.MASTER_MODEL, prompt=_INTENT_PROMPT.replace("__QUESTION__", question),
                       json_mode=True, temperature=0.0)
    parsed = llm.parse_json(raw)
    if not parsed:
        return None
    return _validate(parsed)


def _validate(parsed: dict) -> dict[str, Any] | None:
    """Normalize and validate LLM output. Return None if irrecoverable."""
    intent = parsed.get("intent", "")
    if intent not in VALID_INTENTS:
        return None
    return {
        "intent": intent,
        "entities_referenced": parsed.get("entities_referenced") or [],
        "needs_clarification": bool(parsed.get("needs_clarification")),
        "clarification_q": parsed.get("clarification_q") or None,
        "suggestions": parsed.get("suggestions") or [],
    }


# ---------------------------------------------------------------------------
# Top-level classifier
# ---------------------------------------------------------------------------
def classify(question: str) -> dict[str, Any]:
    """Lexical first, LLM fallback. Always returns a valid dict."""
    lex = lexical_classify(question)
    if lex:
        # Only `unclear` needs clarification suggestions; others go direct
        if lex == "unclear":
            return {
                "intent": "unclear",
                "entities_referenced": [],
                "needs_clarification": True,
                "clarification_q": "Want me to narrow down?",
                "suggestions": [
                    "ongoing project status",
                    "open conflicts",
                    "stale rules",
                    "recent events",
                ],
                "source": "lexical",
            }
        return {
            "intent": lex,
            "entities_referenced": [],
            "needs_clarification": False,
            "clarification_q": None,
            "suggestions": [],
            "source": "lexical",
        }

    llm_result = llm_classify(question)
    if llm_result:
        llm_result["source"] = "llm"
        return llm_result

    # Last resort fallback — treat as summary
    log.warning("intent_fallback_to_summary", extra={"question": question[:80]})
    return {
        "intent": "summary",
        "entities_referenced": [],
        "needs_clarification": False,
        "clarification_q": None,
        "suggestions": [],
        "source": "fallback",
    }
