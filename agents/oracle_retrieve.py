"""Per-intent retrievers — return structured sources for the synthesizer.

Each retriever returns a dict:
  {
    "source_blocks": [str, ...],   # each block is a labeled section for the LLM prompt
    "cited_ids":     [str, ...],   # node / chunk ids cited
    "expanded":      {id: node},   # entity nodes pulled (for diag)
    "chunks":        [hit, ...],   # chunk hits (for diag)
  }
"""
from __future__ import annotations

import logging
import re
from typing import Any

import config
from capabilities import dedup, retriever
from core.knowledge_graph import KnowledgeGraph

log = logging.getLogger("hannibal.oracle.retrieve")

K_DEFAULT = 5
K_CHUNKS_HEAVY = 8  # for rule / document intents


def retrieve(
    kg: KnowledgeGraph,
    intent: str,
    question: str,
    entities_referenced: list[str] | None = None,
) -> dict[str, Any]:
    entities_referenced = entities_referenced or []
    if intent == "company":
        return _company(question)
    if intent == "culture":
        return _culture(kg, question)
    if intent == "person":
        return _person(kg, question, entities_referenced)
    if intent == "team":
        return _team(kg, question, entities_referenced)
    if intent == "project":
        return _project(kg, question, entities_referenced)
    if intent == "client":
        return _client(kg, question, entities_referenced)
    if intent == "rule":
        return _rule(kg, question)
    if intent == "event":
        return _event(kg, question, entities_referenced)
    if intent == "document":
        return _document(kg, question)
    if intent == "summary":
        return _summary(kg)
    return {"source_blocks": [], "cited_ids": [], "expanded": {}, "chunks": []}


# ---------------------------------------------------------------------------
def _company(question: str) -> dict[str, Any]:
    """Strictly read self-company identity from company-config.yml. NO chunks."""
    company = config.COMPANY or {}
    identity = company.get("identity") or {}
    leadership = company.get("leadership") or {}
    tools = company.get("tools") or {}
    culture = company.get("culture") or {}

    lines = ["[SELF-COMPANY IDENTITY] — this is the company the system serves."]
    if identity:
        lines.append("identity:")
        for k, v in identity.items():
            if v:
                lines.append(f"  {k}: {v}")
    if leadership:
        lines.append("leadership:")
        for role_key, person in leadership.items():
            if isinstance(person, dict):
                name = person.get("name", "")
                email = person.get("email", "")
                lines.append(f"  {role_key}: {name} <{email}>")
    if tools:
        lines.append("tools:")
        for k, v in tools.items():
            if v:
                lines.append(f"  {k}: {', '.join(v) if isinstance(v, list) else v}")
    if culture:
        lines.append("culture:")
        for k, v in culture.items():
            if v:
                lines.append(f"  {k}: {', '.join(v) if isinstance(v, list) else v}")

    return {
        "source_blocks": ["\n".join(lines)],
        "cited_ids": [f"company-config:{identity.get('name', 'self')}"],
        "expanded": {},
        "chunks": [],
    }


def _culture(kg: KnowledgeGraph, question: str) -> dict[str, Any]:
    # Same as company but also pull Rule nodes with category=value
    base = _company(question)
    value_rules = [
        r for r in kg.list_live("Rule")
        if (r["fields"].get("category") or "").lower() == "value"
    ]
    if value_rules:
        lines = ["[VALUE RULES from knowledge graph]"]
        for r in value_rules:
            f = r["fields"]
            lines.append(f"- ({r['id']}) {f.get('title', '')}: {f.get('content', '')}")
            base["cited_ids"].append(r["id"])
        base["source_blocks"].append("\n".join(lines))
    return base


# ---------------------------------------------------------------------------
def _person(kg: KnowledgeGraph, question: str, entities: list[str]) -> dict[str, Any]:
    # Resolve names from question + entities_referenced
    candidates = _find_persons_by_name(kg, entities + _extract_names(question))
    if not candidates:
        # Fall back to vector search on Person nodes
        hits = kg.search(question, k=K_DEFAULT, entity_type="Person")
        candidates = [kg.get_live(h["node_id"]) for h in hits]
        candidates = [c for c in candidates if c]
    result = _build_entity_block(kg, candidates, label="PERSON")
    # Safety net — if question references a leadership role title, include the
    # leadership block from company-config.yml so the synthesizer has the answer
    # even if no matching Person node exists.
    if _mentions_leadership_role(question):
        leadership = (config.COMPANY or {}).get("leadership") or {}
        if leadership:
            lines = ["[LEADERSHIP from company-config.yml]"]
            for role_key, person in leadership.items():
                if isinstance(person, dict):
                    nm = person.get("name", "")
                    em = person.get("email", "")
                    lines.append(f"- {role_key}: {nm} <{em}>")
            result["source_blocks"].insert(0, "\n".join(lines))
            result["cited_ids"].append("company-config:leadership")
    return result


_LEADERSHIP_TOKENS = {
    "ceo", "cto", "cfo", "coo", "founder", "founders",
    "hr lead", "hr head", "head of hr", "head of engineering",
    "head of ops", "head of operations", "head of sales",
    "head of marketing", "head of finance", "leadership",
}


def _mentions_leadership_role(question: str) -> bool:
    q = question.lower()
    return any(tok in q for tok in _LEADERSHIP_TOKENS)


def _team(kg: KnowledgeGraph, question: str, entities: list[str]) -> dict[str, Any]:
    candidates = _find_by_name(kg, "Team", entities + _extract_names(question))
    if not candidates:
        hits = kg.search(question, k=K_DEFAULT, entity_type="Team")
        candidates = [n for n in (kg.get_live(h["node_id"]) for h in hits) if n]
    # Generic "list teams" / "which teams" → no specific match → return all
    if not candidates or _is_list_query(question, "team"):
        candidates = kg.list_live("Team")
    return _build_entity_block(kg, candidates, label="TEAM")


def _project(kg: KnowledgeGraph, question: str, entities: list[str]) -> dict[str, Any]:
    candidates = _find_by_name(kg, "Project", entities + _extract_names(question))
    if not candidates:
        hits = kg.search(question, k=K_DEFAULT, entity_type="Project")
        candidates = [n for n in (kg.get_live(h["node_id"]) for h in hits) if n]
    # Generic "which projects" / "list projects" / "ongoing projects" → all
    if not candidates or _is_list_query(question, "project"):
        candidates = kg.list_live("Project")
    return _build_entity_block(kg, candidates, label="PROJECT")


def _client(kg: KnowledgeGraph, question: str, entities: list[str]) -> dict[str, Any]:
    candidates = _find_by_name(kg, "Client", entities + _extract_names(question))
    if not candidates or _is_list_query(question, "client"):
        candidates = kg.list_live("Client")
    return _build_entity_block(kg, candidates, label="CLIENT")


_LIST_PATTERNS = re.compile(
    r"\b(which|what|list|all|every|ongoing|active|current|open)\b",
    re.I,
)


def _is_list_query(question: str, entity_type: str) -> bool:
    """Detect 'which X are ...' / 'list all X' / 'ongoing X' style queries.

    These should return the full set of that type so the LLM can summarize/filter.
    """
    q = question.lower()
    if entity_type not in q and f"{entity_type}s" not in q:
        return False
    return bool(_LIST_PATTERNS.search(question))


def _rule(kg: KnowledgeGraph, question: str) -> dict[str, Any]:
    """Rules need both KG and document chunks (policy text often in docs)."""
    rule_hits = kg.search(question, k=K_CHUNKS_HEAVY, entity_type="Rule")
    rules = [n for n in (kg.get_live(h["node_id"]) for h in rule_hits) if n]
    chunks = retriever.hybrid_search_chunks(kg, question, k=K_CHUNKS_HEAVY)
    blocks: list[str] = []
    cited: list[str] = []
    if rules:
        lines = ["[RULE entities]"]
        for r in rules:
            f = r["fields"]
            lines.append(f"- ({r['id']}) [{f.get('category', '?')}] {f.get('title', '')}: {f.get('content', '')}")
            cited.append(r["id"])
        blocks.append("\n".join(lines))
    if chunks:
        blocks.append(_chunk_block(chunks, cited))
    return {"source_blocks": blocks, "cited_ids": cited,
            "expanded": {r["id"]: r for r in rules}, "chunks": chunks}


def _event(kg: KnowledgeGraph, question: str, entities: list[str]) -> dict[str, Any]:
    candidates = _find_by_name(kg, "Event", entities + _extract_names(question))
    if not candidates:
        hits = kg.search(question, k=K_DEFAULT, entity_type="Event")
        candidates = [n for n in (kg.get_live(h["node_id"]) for h in hits) if n]
    return _build_entity_block(kg, candidates, label="EVENT")


def _document(kg: KnowledgeGraph, question: str) -> dict[str, Any]:
    """Document-content questions — chunk search dominant."""
    chunks = retriever.hybrid_search_chunks(kg, question, k=K_CHUNKS_HEAVY)
    cited: list[str] = []
    blocks = [_chunk_block(chunks, cited)] if chunks else []
    return {"source_blocks": blocks, "cited_ids": cited, "expanded": {}, "chunks": chunks}


def _summary(kg: KnowledgeGraph) -> dict[str, Any]:
    """Full inventory grouped by type."""
    blocks: list[str] = []
    cited: list[str] = []
    for et in ("Person", "Team", "Project", "Client", "Rule", "Event", "Document"):
        nodes = kg.list_live(et)
        if not nodes:
            continue
        lines = [f"[{et} ({len(nodes)})]"]
        for n in nodes[:30]:
            f = n["fields"]
            label = f.get("name") or f.get("title") or "(unnamed)"
            extras = []
            for k in ("kind", "email", "role", "status", "date", "category"):
                if f.get(k):
                    extras.append(f"{k}={f[k]}")
            extra_s = "  " + ", ".join(extras) if extras else ""
            lines.append(f"- ({n['id']}) {label}{extra_s}")
            cited.append(n["id"])
        blocks.append("\n".join(lines))
    return {"source_blocks": blocks, "cited_ids": cited, "expanded": {}, "chunks": []}


# ---------------------------------------------------------------------------
def _resolve_id_fields(kg: KnowledgeGraph, fields: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of fields with any `*_id` value augmented to `name (id)`.

    Makes the source block readable to the LLM (and to humans) without losing
    the id for citation purposes.
    """
    out: dict[str, Any] = {}
    for k, v in fields.items():
        if not v or not isinstance(v, str) or not k.endswith("_id"):
            out[k] = v
            continue
        ref = kg.get_live(v)
        if ref:
            name = ref["fields"].get("name") or ref["fields"].get("title") or v
            out[k] = f"{name} ({v})"
        else:
            out[k] = v
    return out


def _build_entity_block(
    kg: KnowledgeGraph, candidates: list[dict], label: str
) -> dict[str, Any]:
    """Build a richly-labeled source block per entity with explicit relationship sections."""
    if not candidates:
        return {"source_blocks": [], "cited_ids": [], "expanded": {}, "chunks": []}
    expanded: dict[str, dict] = {}
    blocks: list[str] = []
    cited: list[str] = []
    for node in candidates:
        expanded[node["id"]] = node
        block, neighbors = _format_entity(kg, node)
        blocks.append(block)
        for nid in neighbors:
            if nid not in expanded:
                nb = kg.get_live(nid)
                if nb:
                    expanded[nid] = nb
        cited.append(node["id"])
        cited.extend(neighbors)

    # Light chunk pull — name-based, top-3 per first 3 candidates
    chunks: list[dict] = []
    for node in candidates[:3]:
        name = node["fields"].get("name") or node["fields"].get("title") or ""
        if name:
            ch = retriever.hybrid_search_chunks(kg, name, k=3)
            chunks.extend(ch)
    if chunks:
        blocks.append(_chunk_block(chunks, []))
        cited.extend(c["chunk_id"] for c in chunks)
    return {"source_blocks": blocks, "cited_ids": cited, "expanded": expanded, "chunks": chunks}


def _format_entity(kg: KnowledgeGraph, node: dict) -> tuple[str, list[str]]:
    """Return (formatted_block, list_of_neighbor_ids)."""
    et = node["entity_type"]
    f = _resolve_id_fields(kg, node["fields"])
    name = f.get("name") or f.get("title") or "(unnamed)"
    nid = node["id"]
    neighbors: list[str] = []
    lines = [f"[{et}: {name}]  id={nid}"]

    # Core fields (skip name/title since they're in the header)
    field_lines: list[str] = []
    for k, v in f.items():
        if k in ("name", "title") or not v:
            continue
        # Skip overly long lists; let dedicated sections handle them
        if isinstance(v, list) and len(v) > 0:
            field_lines.append(f"  {k}: {', '.join(str(x) for x in v)}")
        else:
            field_lines.append(f"  {k}: {v}")
    if field_lines:
        lines.append("FIELDS:")
        lines.extend(field_lines)

    # Edges grouped semantically
    sections: dict[str, list[str]] = {
        "MEMBERS":   [],   # Person --MEMBER_OF--> this Team
        "TEAMS":     [],   # this Person --MEMBER_OF--> Team
        "PROJECTS":  [],   # Team/Person --WORKS_ON--> Project  OR  Team --RUNS--> Project
        "CLIENT":    [],   # this Project --OWNED_BY--> Client
        "CLIENTS_OF":[],   # Projects owned by this Client
        "EVENTS":    [],   # Person --PARTICIPATED_IN--> Event
        "DOCUMENTS": [],   # Person --AUTHORED--> Document
        "SUB_TEAMS": [],   # Team --CHILD_OF--> this Team (children)
        "PARENT_TEAM":[],  # this Team --CHILD_OF--> Team (parent)
        "RULES":     [],   # Rules --OWNED_BY--> this Person/Team
        "NOTIFIES":  [],   # Rule --NOTIFY--> this Person
        "OTHER":     [],
    }

    for edge in kg.neighbors(nid):
        other_id = edge["to_id"] if edge["from_id"] == nid else edge["from_id"]
        other = kg.get_live(other_id)
        if not other:
            continue
        neighbors.append(other_id)
        other_label = other["fields"].get("name") or other["fields"].get("title") or "(unnamed)"
        et_other = other["entity_type"]
        edge_type = edge["type"]
        role = (edge["properties"] or {}).get("role", "")
        subs = (edge["properties"] or {}).get("sub_roles") or []
        tag = role + (f" · {', '.join(subs)}" if subs else "")
        tag_str = f" — {tag}" if tag else ""

        # this node is FROM → outgoing
        outgoing = edge["from_id"] == nid

        if edge_type == "MEMBER_OF":
            if outgoing and et == "Person":
                sections["TEAMS"].append(f"  • {other_label} ({other_id}){tag_str}")
            elif not outgoing and et == "Team":
                sections["MEMBERS"].append(f"  • {other_label} ({other_id}){tag_str}")
        elif edge_type in ("WORKS_ON", "RUNS"):
            if outgoing:
                sections["PROJECTS"].append(f"  • {other_label} ({other_id}){tag_str}")
            else:
                # Other works on us (we're the Project)
                sections["PROJECTS"].append(f"  • (worker) {other_label} ({other_id}){tag_str}")
        elif edge_type == "OWNED_BY":
            if outgoing and et == "Project" and et_other == "Client":
                sections["CLIENT"].append(f"  • {other_label} ({other_id})")
            elif not outgoing and et == "Client" and et_other == "Project":
                sections["CLIENTS_OF"].append(f"  • {other_label} ({other_id})")
            else:
                sections["OTHER"].append(f"  {edge_type}: {other_label} ({other_id}){tag_str}")
        elif edge_type == "PARTICIPATED_IN" and outgoing:
            sections["EVENTS"].append(f"  • {other_label} ({other_id})")
        elif edge_type == "AUTHORED" and outgoing:
            sections["DOCUMENTS"].append(f"  • {other_label} ({other_id})")
        elif edge_type == "CHILD_OF":
            if outgoing:
                sections["PARENT_TEAM"].append(f"  • {other_label} ({other_id})")
            else:
                sections["SUB_TEAMS"].append(f"  • {other_label} ({other_id})")
        elif edge_type == "BELONGS_TO_CLIENT" and outgoing:
            sections["CLIENT"].append(f"  • {other_label} ({other_id})")
        elif edge_type == "NOTIFY":
            sections["NOTIFIES"].append(f"  • {other_label} ({other_id})")
        else:
            sections["OTHER"].append(
                f"  {edge_type}: {other_label} ({other_id}){tag_str}"
            )

    for sec_name, items in sections.items():
        if not items:
            continue
        lines.append(f"{sec_name}:")
        lines.extend(items)

    return "\n".join(lines), neighbors


def _chunk_block(chunks: list[dict], cited: list[str]) -> str:
    lines = ["[DOCUMENT QUOTES]"]
    for ch in chunks:
        title = ch.get("doc_title") or ch.get("doc_id", "?")
        ordinal = ch.get("ordinal", "?")
        snippet = (ch.get("text") or "").strip()
        if len(snippet) > 500:
            snippet = snippet[:500] + "…"
        lines.append(f'- ({title}, chunk {ordinal})\n  "{snippet}"')
        cited.append(ch["chunk_id"])
    return "\n".join(lines)


# ---------------------------------------------------------------------------
def _find_by_name(kg: KnowledgeGraph, entity_type: str, names: list[str]) -> list[dict]:
    live = kg.list_live(entity_type)
    matched: list[dict] = []
    for name in names:
        for n in live:
            if dedup.tokens_match(dedup.normalize_tokens(name),
                                  dedup.normalize_tokens(n["fields"].get("name"))):
                if n not in matched:
                    matched.append(n)
                break
    return matched


def _find_persons_by_name(kg: KnowledgeGraph, names: list[str]) -> list[dict]:
    return _find_by_name(kg, "Person", names)


def _extract_names(question: str) -> list[str]:
    """Crude noun-phrase extraction — capitalized word sequences."""
    import re
    # Match Title Case sequences (handles multi-word names)
    pat = re.compile(r"\b[A-Z][a-zà-ÿ]+(?:\s+[A-Z][a-zà-ÿ]+){0,3}\b")
    return pat.findall(question)
