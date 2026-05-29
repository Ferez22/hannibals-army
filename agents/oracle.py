"""ORACLE — answers questions via hybrid search (vector + graph traversal)."""
from __future__ import annotations

import logging
from typing import Any

import config
from agents.base_agent import AgentResult, BaseAgent
from core.knowledge_graph import KnowledgeGraph

log = logging.getLogger("hannibal.oracle")


ANSWER_PROMPT = """You are ORACLE. Answer the question using ONLY the sources below. The sources include knowledge-graph entities (with ids like `person_abc123`) and document quotes (with citations like `(Handbook.docx, chunk 3)`).

Rules:
- Read every source carefully — document quotes may contain the answer even if it's a single line or a small detail.
- Quote or paraphrase relevant text from the document quotes.
- Cite every fact you use, in parentheses.
- ONLY if NONE of the sources contain anything relevant to the question, reply exactly: "I don't know based on what's in the knowledge graph."

QUESTION:
__QUESTION__

SOURCES:
__SOURCES__

ANSWER:"""


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

        # Hybrid retrieval: entities + document chunks
        node_hits = self.kg.search(question, k=k)
        chunk_hits = self.kg.search_chunks(question, k=k)
        log.info(
            "oracle_hits",
            extra={"nodes": len(node_hits), "chunks": len(chunk_hits)},
        )

        if not node_hits and not chunk_hits:
            return self._summary_answer(question)

        # Expand 1-hop neighborhood per node seed
        expanded: dict[str, dict] = {}
        for hit in node_hits:
            node = self.kg.get_live(hit["node_id"])
            if not node:
                continue
            expanded[node["id"]] = node
            for edge in self.kg.neighbors(node["id"]):
                neighbor_id = edge["to_id"] if edge["from_id"] == node["id"] else edge["from_id"]
                neighbor = self.kg.get_live(neighbor_id)
                if neighbor and neighbor["id"] not in expanded:
                    expanded[neighbor["id"]] = neighbor

        # Build sources block: entities + chunks
        source_lines: list[str] = []
        cited_ids: list[str] = []

        if expanded:
            source_lines.append("[Knowledge graph entities]")
            for nid, node in expanded.items():
                f = node["fields"]
                summary = f.get("name") or f.get("title") or "(unnamed)"
                extras = {k: v for k, v in f.items() if k not in ("name", "title") and v}
                source_lines.append(
                    f"- ({nid}) [{node['entity_type']}] {summary}  {extras if extras else ''}"
                )
                cited_ids.append(nid)
            for nid in list(expanded.keys()):
                for edge in self.kg.neighbors(nid):
                    if edge["from_id"] in expanded and edge["to_id"] in expanded:
                        role = edge["properties"].get("role", "")
                        role_s = f" (role: {role})" if role else ""
                        source_lines.append(
                            f"  edge: ({edge['from_id']}) -{edge['type']}-> ({edge['to_id']}){role_s}"
                        )

        if chunk_hits:
            source_lines.append("\n[Document quotes]")
            for ch in chunk_hits:
                doc_title = ch.get("doc_title") or ch.get("doc_id")
                ordinal = ch.get("ordinal", "?")
                snippet = ch.get("text", "").strip()
                if len(snippet) > 600:
                    snippet = snippet[:600] + "…"
                citation = f"({doc_title}, chunk {ordinal})"
                source_lines.append(f"- {citation}\n  \"{snippet}\"")
                cited_ids.append(ch["chunk_id"])

        sources_text = "\n".join(source_lines)
        answer = _call_llm(question, sources_text)
        diag = {
            "entities_found": len(node_hits),
            "chunks_found": len(chunk_hits),
            "entities_expanded": len(expanded),
            "top_chunk_distances": [round(ch["distance"], 3) for ch in chunk_hits[:3]],
            "top_chunk_previews": [
                f"({ch.get('doc_title')}, ch {ch.get('ordinal')}): {ch.get('text', '')[:120]!r}"
                for ch in chunk_hits[:3]
            ],
        }
        return AgentResult(
            True,
            data={"answer": answer, "diag": diag},
            cited_nodes=cited_ids,
        )


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
                data={"answer": "The knowledge graph is empty. Ingest some documents first.",
                      "diag": {"entities_found": 0, "chunks_found": 0}},
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
        return AgentResult(
            True,
            data={"answer": answer, "diag": {"mode": "summary", "entities_in_inventory": len(all_ids)}},
            cited_nodes=all_ids,
        )


def _call_llm(question: str, sources_text: str) -> str:
    import ollama

    prompt = ANSWER_PROMPT.replace("__QUESTION__", question).replace("__SOURCES__", sources_text)
    response = ollama.generate(
        model=config.MASTER_MODEL,
        prompt=prompt,
        options={"temperature": 0.0},
    )
    return response.get("response", "").strip()


ORACLE = Oracle()
