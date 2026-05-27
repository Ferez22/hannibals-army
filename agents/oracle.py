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

        # Vector search → seed nodes
        hits = self.kg.search(question, k=k)
        log.info("oracle_vector_hits", extra={"count": len(hits)})

        if not hits:
            return AgentResult(
                True,
                data="I don't know based on what's in the knowledge graph (no relevant nodes found).",
                cited_nodes=[],
            )

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
