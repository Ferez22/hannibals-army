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


def synthesize(
    *,
    question: str,
    intent: str,
    source_blocks: list[str],
) -> str:
    if not source_blocks:
        return (
            "I don't have anything in the knowledge graph related to that yet. "
            "Try ingesting more docs, or check what's there in the Browser screen."
        )

    addon = _INTENT_ADDONS.get(intent, "")
    sources = "\n\n".join(source_blocks)
    prompt = f"""{_SYSTEM}

INTENT: {intent}
{addon}

QUESTION:
{question}

SOURCES:
{sources}

ANSWER:"""

    model = _model_for_intent(intent)
    log.info("synth", extra={"intent": intent, "model": model, "blocks": len(source_blocks)})
    answer = llm.generate(model=model, prompt=prompt, temperature=0.0, max_tokens=400)
    if not answer:
        # Fallback to local if cloud failed
        if model == "openai":
            log.warning("synth_cloud_failed_fallback_local")
            answer = llm.generate(model=config.MASTER_MODEL, prompt=prompt,
                                  temperature=0.0, max_tokens=400)
    return answer or "I don't have enough in the knowledge graph to answer that confidently."


def _model_for_intent(intent: str) -> str:
    """Pick model per intent. Falls back to local if OpenAI key missing."""
    target = config.SYNTHESIS_MODEL_MAP.get(intent)
    if target == "openai" and llm.openai_available():
        return "openai"
    return config.MASTER_MODEL
