"""ORACLE synthesizer — turns retrieved sources into a cited answer.

Per-intent prompts. Model auto-switch (Ollama default; OpenAI for rule/project
when key present).
"""
from __future__ import annotations

import logging

import config
from capabilities import llm

log = logging.getLogger("hannibal.oracle.synth")


_SYSTEM = """You are ORACLE, the company knowledge oracle. Be helpful and concrete.

Guidelines:
- Use the sources below as your primary input. Pull together facts across them when they're about the same thing — that's expected.
- Cite the source ids in parentheses where helpful (e.g. (person_abc123) or (doc_title, chunk N)). Citations are encouraged, not mandatory for every line.
- If something is in the sources, USE it. Don't say you don't know when the answer is right there in a relevant section.
- If two sources truly contradict on a fact, flag it ("one source says X, another says Y") and pick the more authoritative one if possible. Otherwise use what you have.
- If sources genuinely have nothing on the question, then say "I don't have enough in the knowledge graph for that — try ingesting more docs or check the Browser screen."
- Be concise but complete. Bullet lists are fine for enumerations (members, projects, etc).
- For team / project / person queries: always list what's known — members, leads, projects, status, dates — even if the user asked a narrow question.
"""


_INTENT_ADDONS: dict[str, str] = {
    "company": (
        "This question is about the SELF-COMPANY (the company this knowledge graph belongs to). "
        "Answer ONLY from the SELF-COMPANY IDENTITY block. Do NOT confuse with any Client."
    ),
    "person": "Focus on the named person. Include their teams, roles, sub-roles, projects.",
    "team": "Focus on the team. List members + linked projects.",
    "project": (
        "Focus on the project. Always include status, client (if external), teams involved, "
        "leads, key dates."
    ),
    "client": "Focus on the client. Linked projects, contact, status.",
    "rule": (
        "Quote the rule content verbatim if possible. Cite rule id AND any doc-quote source. "
        "If multiple rules apply, list them."
    ),
    "event": "When + outcome + participants if known.",
    "document": "Quote the relevant chunk(s). Cite (doc_title, chunk N).",
    "culture": "Answer from values + culture + leadership sections.",
    "summary": "Structured by entity type. Don't go past what's listed.",
}


UNCONFIRMED_BANNER = (
    "ℹ️ *Some entries below haven't been reviewed by an admin yet — "
    "the underlying facts may be inaccurate. Confirm them in the Audit screen.*"
)

# Character cap per injected prior message to keep prompt bounded
RECENT_MSG_CHAR_CAP = 500


def _render_conversation_context(recent_turns: list[dict] | None) -> str:
    """Format prior messages as a CONVERSATION CONTEXT block.

    Each msg: dict with 'role' ('user'|'assistant') + 'content'. Older first,
    newest last. Returns '' when no turns to render."""
    if not recent_turns:
        return ""
    lines = ["CONVERSATION CONTEXT (oldest → newest, use to resolve follow-ups):"]
    for msg in recent_turns:
        role = msg.get("role", "?")
        content = (msg.get("content") or "").strip()
        if not content:
            continue
        if len(content) > RECENT_MSG_CHAR_CAP:
            content = content[:RECENT_MSG_CHAR_CAP] + "…"
        lines.append(f"  {role}: {content}")
    return "\n".join(lines) if len(lines) > 1 else ""


def synthesize(
    *,
    question: str,
    intent: str,
    source_blocks: list[str],
    has_unconfirmed: bool = False,
    persona_block: str = "",
    recent_turns: list[dict] | None = None,
) -> str:
    conv_block = _render_conversation_context(recent_turns)
    persona_section = f"\n{persona_block}\n" if persona_block else ""
    conv_section = f"\n{conv_block}\n" if conv_block else ""

    # Phase 12: synth may still answer using PERSONA + CONVERSATION CONTEXT
    # even when retrieval is empty (e.g. follow-up "her email?" referring to
    # someone from a prior turn). Only bail out when nothing at all is in scope.
    if not source_blocks and not persona_block and not conv_block:
        return (
            "I don't have anything in the knowledge graph related to that yet. "
            "Try ingesting more docs, or check what's there in the Browser screen."
        )

    addon = _INTENT_ADDONS.get(intent, "")
    sources = "\n\n".join(source_blocks) if source_blocks else "(no fresh sources for this question — rely on context above)"

    prompt = f"""{_SYSTEM}

INTENT: {intent}
{addon}
{persona_section}{conv_section}
QUESTION:
{question}

SOURCES:
{sources}

ANSWER:"""

    model = _model_for_intent(intent)
    log.info("synth", extra={"intent": intent, "model": model, "blocks": len(source_blocks),
                              "has_unconfirmed": has_unconfirmed})
    answer = llm.generate(model=model, prompt=prompt, temperature=0.0, max_tokens=400)
    if not answer:
        # Fallback to local if cloud failed
        if model == "openai":
            log.warning("synth_cloud_failed_fallback_local")
            answer = llm.generate(model=config.MASTER_MODEL, prompt=prompt,
                                  temperature=0.0, max_tokens=400)
    final = answer or "I don't have enough in the knowledge graph to answer that confidently."
    if has_unconfirmed and answer:
        final = f"{UNCONFIRMED_BANNER}\n\n{final}"
    return final


def _model_for_intent(intent: str) -> str:
    """Pick model per intent. Falls back to local if OpenAI key missing."""
    target = config.SYNTHESIS_MODEL_MAP.get(intent)
    if target == "openai" and llm.openai_available():
        return "openai"
    return config.MASTER_MODEL
