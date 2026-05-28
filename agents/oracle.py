"""ORACLE — answers questions via hybrid search (vector + graph traversal)."""
from __future__ import annotations

import logging
from typing import Any

import config
from agents.base_agent import AgentResult, BaseAgent
from core.knowledge_graph import KnowledgeGraph

log = logging.getLogger("hannibal.oracle")


ANSWER_PROMPT = """You are ORACLE, the company knowledge oracle. Answer the question STRICTLY from the cited nodes below. Do not invent facts. If the cited nodes do not contain the answer, say "I don't know based on what's in the knowledge graph."

QUESTION:
__QUESTION__

CITED NODES:
__NODES__

ANSWER (concise, 1-3 sentences, cite node ids in parentheses like (person_abc123)):"""


SUMMARY_PROMPT = """You are ORACLE. Below is the FULL inventory of the company knowledge graph, grouped by entity type. Give a concise, structured answer to the question using this inventory. Do not invent facts beyond what is listed.

QUESTION:
__QUESTION__

INVENTORY:
__INVENTORY__

ANSWER (organized by category if useful, cite node ids like (person_abc123)):"""


SUMMARY_TRIGGERS = (
    "tell me about",
    "what do you know",
    "what can you tell",
    "overview",
    "summary",
    "summarize",
    "describe the company",
    "who works",
    "list all",
    "show all",
    "what teams",
    "what projects",
)


def _is_summary_question(question: str) -> bool:
    q = question.lower().strip()
    return any(t in q for t in SUMMARY_TRIGGERS)


class Oracle(BaseAgent):
    name = "ORACLE"
    tagline = "query engine — answers from cited nodes only"
    persona = "Oracle queries the live knowledge graph."

    def __init__(self, kg: KnowledgeGraph | None = None) -> None:
        super().__init__(kg=kg)

    def invoke(self, task: dict[str, Any]) -> AgentResult:
        """task: {"question": str, "k": int (optional)}"""
        question = task.get("question")
        k = task.get("k", 5)
        if not question:
            return AgentResult(False, error="missing 'question'")
        if self.kg is None:
            return AgentResult(False, error="oracle has no KG bound")

        # Summary mode: broad questions get the full inventory
        if _is_summary_question(question):
            return self._summary_answer(question)

        # Vector search → seed nodes
        hits = self.kg.search(question, k=k)
        log.info("oracle_vector_hits", extra={"count": len(hits)})

        if not hits:
            # Fallback: also try summary mode if no hits
            return self._summary_answer(question)

        # Expand 1-hop neighborhood per seed
        expanded: dict[str, dict] = {}
        for hit in hits:
            node = self.kg.get_live(hit["node_id"])
            if not node:
                continue
            expanded[node["id"]] = node
            for edge in self.kg.neighbors(node["id"]):
                neighbor_id = edge["to_id"] if edge["from_id"] == node["id"] else edge["from_id"]
                neighbor = self.kg.get_live(neighbor_id)
                if neighbor and neighbor["id"] not in expanded:
                    expanded[neighbor["id"]] = neighbor

        # Build citation block
        nodes_text_lines: list[str] = []
        for nid, node in expanded.items():
            f = node["fields"]
            summary = f.get("name") or f.get("title") or "(unnamed)"
            extras = {k: v for k, v in f.items() if k not in ("name", "title") and v}
            nodes_text_lines.append(
                f"- ({nid}) [{node['entity_type']}] {summary}  {extras if extras else ''}"
            )

        # Add edges
        for nid, node in expanded.items():
            for edge in self.kg.neighbors(nid):
                if edge["from_id"] in expanded and edge["to_id"] in expanded:
                    role = edge["properties"].get("role", "")
                    role_s = f" (role: {role})" if role else ""
                    nodes_text_lines.append(
                        f"  edge: ({edge['from_id']}) -{edge['type']}-> ({edge['to_id']}){role_s}"
                    )

        nodes_text = "\n".join(nodes_text_lines)
        answer = _call_llm(question, nodes_text)
        return AgentResult(True, data=answer, cited_nodes=list(expanded.keys()))


    def _summary_answer(self, question: str) -> AgentResult:
        """Inventory-based answer for broad questions."""
        if self.kg is None:
            return AgentResult(False, error="oracle has no KG bound")
        sections: list[str] = []
        all_ids: list[str] = []
        for et in ("Person", "Team", "Project", "Rule", "Event", "Document"):
            nodes = self.kg.list_live(et)
            if not nodes:
                continue
            sections.append(f"## {et} ({len(nodes)})")
            for n in nodes[:30]:  # cap per type to keep prompt manageable
                f = n["fields"]
                label = f.get("name") or f.get("title") or "(unnamed)"
                extras: list[str] = []
                for key in ("email", "role", "status", "date", "type", "category"):
                    if f.get(key):
                        extras.append(f"{key}={f[key]}")
                extra_s = "  " + ", ".join(extras) if extras else ""
                sections.append(f"- ({n['id']}) {label}{extra_s}")
                all_ids.append(n["id"])

        if not sections:
            return AgentResult(
                True,
                data="The knowledge graph is empty. Ingest some documents first.",
                cited_nodes=[],
            )

        inventory_text = "\n".join(sections)
        log.info("oracle_summary_mode", extra={"entities": len(all_ids)})
        prompt = SUMMARY_PROMPT.replace("__QUESTION__", question).replace("__INVENTORY__", inventory_text)
        import ollama
        response = ollama.generate(
            model=config.MASTER_MODEL,
            prompt=prompt,
            options={"temperature": 0.0},
        )
        answer = response.get("response", "").strip()
        return AgentResult(True, data=answer, cited_nodes=all_ids)


def _call_llm(question: str, nodes_text: str) -> str:
    import ollama

    prompt = ANSWER_PROMPT.replace("__QUESTION__", question).replace("__NODES__", nodes_text)
    response = ollama.generate(
        model=config.MASTER_MODEL,
        prompt=prompt,
        options={"temperature": 0.0},
    )
    return response.get("response", "").strip()


ORACLE = Oracle()
