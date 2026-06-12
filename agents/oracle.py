"""ORACLE — top-level orchestrator.

Pipeline: classify intent → retrieve sources per intent → synthesize cited answer.
Clarification path: if intent classifier flags `needs_clarification`, return suggestions for the UI to render as buttons.
"""
from __future__ import annotations

import logging
from typing import Any

from agents import oracle_intent, oracle_retrieve, oracle_synth
from agents.base_agent import AgentResult, BaseAgent
from core.knowledge_graph import KnowledgeGraph

log = logging.getLogger("hannibal.oracle")


class Oracle(BaseAgent):
    name = "ORACLE"
    tagline = "query engine — intent-routed, cited"
    persona = "Oracle queries the live knowledge graph."

    def __init__(self, kg: KnowledgeGraph | None = None) -> None:
        super().__init__(kg=kg)

    def invoke(self, task: dict[str, Any]) -> AgentResult:
        import config
        from capabilities import persona_store

        question = (task.get("question") or "").strip()
        if not question:
            return AgentResult(False, error="missing 'question'")
        if self.kg is None:
            return AgentResult(False, error="oracle has no KG bound")

        # Sender identity (Phase 10A) — Telegram path or TUI path injects sender_person_id.
        # Unknown sender = UNKNOWN_SENDER_TIER (everyone) — content access still filtered.
        sender_person_id: str | None = task.get("sender_person_id")
        sender_tier: str = task.get("sender_tier") or config.UNKNOWN_SENDER_TIER
        sender_tier_rank = config.tier_rank(sender_tier)

        # Phase 12 — Conversation memory.
        # `conversation_id`: caller (Telegram bot / TUI) opens/reuses a convo and
        # passes the id. Oracle pulls recent turns + persona from there.
        conversation_id: int | None = task.get("conversation_id")
        recent_turns: list[dict] = []
        if conversation_id:
            try:
                recent_turns = self.kg.recent_messages(conversation_id, limit=6)
            except Exception as e:
                log.warning("recent_messages_failed", extra={"error": str(e)})

        # Persona injection — sender's own card. Other people's cards are NEVER
        # injected here; the requesting agent decides whose persona to load.
        persona_block = ""
        if sender_person_id:
            persona_data = persona_store.load_persona(sender_person_id)
            if persona_data:
                persona_block = persona_store.render_persona_for_prompt(persona_data)

        # 1) Classify intent
        intent_info = oracle_intent.classify(question)
        intent = intent_info["intent"]
        log.info(
            "intent_classified",
            extra={"intent": intent, "source": intent_info.get("source"),
                   "needs_clarification": intent_info["needs_clarification"],
                   "sender_tier": sender_tier},
        )

        # 2) Clarification short-circuit — skipped when conv context exists, so
        # follow-ups like "her email?" resolve via prior turns instead of asking
        # the user to repeat themselves.
        if intent_info["needs_clarification"] and not recent_turns:
            return AgentResult(
                True,
                data={
                    "answer": intent_info["clarification_q"] or "Could you narrow that down?",
                    "diag": {"intent": intent, "mode": "clarification"},
                    "suggestions": intent_info["suggestions"],
                },
                cited_nodes=[],
            )

        # 3) Retrieve per intent
        retrieval = oracle_retrieve.retrieve(
            self.kg, intent, question,
            entities_referenced=intent_info["entities_referenced"],
            sender_tier_rank=sender_tier_rank,
            sender_person_id=sender_person_id,
        )

        # 4) Synthesize answer
        answer = oracle_synth.synthesize(
            question=question, intent=intent,
            source_blocks=retrieval["source_blocks"],
            has_unconfirmed=retrieval.get("has_unconfirmed", False),
            persona_block=persona_block,
            recent_turns=recent_turns,
        )

        diag = {
            "intent": intent,
            "source": intent_info.get("source"),
            "blocks": len(retrieval["source_blocks"]),
            "entities_expanded": len(retrieval.get("expanded") or {}),
            "chunks_found": len(retrieval.get("chunks") or []),
            "top_chunk_previews": [
                f"({ch.get('doc_title')}, ch {ch.get('ordinal')}): {ch.get('text', '')[:120]!r}"
                for ch in (retrieval.get("chunks") or [])[:3]
            ],
        }
        return AgentResult(
            True,
            data={"answer": answer, "diag": diag},
            cited_nodes=retrieval["cited_ids"],
        )


ORACLE = Oracle()
