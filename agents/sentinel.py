"""SENTINEL — document tier classifier agent.

Runs post-extraction, pre-promotion. Takes a Document candidate (title + raw
text) and proposes:
  - doc_kind (contract / private / general / presentation / report / policy)
  - tier (ceo / c_level / director / manager / everyone)
  - reason (short string for the admin to audit)
  - confidence (0..1)

SENTINEL never writes to the live graph. It annotates staging documents; the
Pending screen surfaces the proposal for CEO confirmation.

Pipeline slot (see core/ingestion_pipeline.py): CARTOGRAPHER extracts → for each
Document entity, SENTINEL.classify() is called → result is merged into the
staged Document's fields (tier, doc_kind, tier_reason). Promotion path leaves
`tier_confirmed_*` empty until the admin confirms in Pending.
"""
from __future__ import annotations

import logging
from typing import Any

from agents.base_agent import AgentResult, BaseAgent
from capabilities import tier_classify

log = logging.getLogger("hannibal.sentinel")


class Sentinel(BaseAgent):
    name = "SENTINEL"
    tagline = "document tier classifier — proposes, admin confirms"
    persona = "Sentinel guards document access by proposing tiers, never asserting them."

    def invoke(self, task: dict[str, Any]) -> AgentResult:
        title = (task.get("title") or "").strip()
        text = task.get("text") or ""
        if not title and not text:
            return AgentResult(False, error="missing 'title' and 'text'")

        # `kg` is taken from self.kg first, then task override.
        kg = task.get("kg") or self.kg
        result = tier_classify.classify(title=title, text=text, kg=kg)
        log.info(
            "sentinel_classified",
            extra={
                "title": title[:80],
                "doc_kind": result["doc_kind"],
                "tier": result["tier"],
                "source": result["source"],
                "confidence": result["confidence"],
            },
        )
        return AgentResult(True, data=result)


SENTINEL = Sentinel()
