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
        question = (task.get("question") or "").strip()
        if not question:
            return AgentResult(False, error="missing 'question'")
        if self.kg is None:
            return AgentResult(False, error="oracle has no KG bound")

        # 1) Classify intent
        intent_info = oracle_intent.classify(question)
        intent = intent_info["intent"]
        log.info(
            "intent_classified",
            extra={"intent": intent, "source": intent_info.get("source"),
                   "needs_clarification": intent_info["needs_clarification"]},
        )

        # 2) Clarification short-circuit
        if intent_info["needs_clarification"]:
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
            self.kg, intent, question, entities_referenced=intent_info["entities_referenced"]
        )

        # 4) Synthesize answer
        answer = oracle_synth.synthesize(
            question=question, intent=intent, source_blocks=retrieval["source_blocks"]
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
