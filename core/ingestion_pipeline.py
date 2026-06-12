"""Ingestion pipeline — RAGNAR → Document live node → CARTOGRAPHER → KG.

Rejects if SystemStatus.ingestion_paused.
"""
from __future__ import annotations

import logging
from datetime import datetime

import config
from agents.base_agent import AgentResult
from agents.cartographer import CARTOGRAPHER
from agents.ragnar import RAGNAR
from capabilities import chunker, extractor
from core.entity_types import RawDocument
from core.knowledge_graph import KnowledgeGraph
from core.system_status import SystemStatus

log = logging.getLogger("hannibal.pipeline")

# Shared KG instance bound to all agents on first call
_KG: KnowledgeGraph | None = None
_STATUS = SystemStatus()


def get_kg() -> KnowledgeGraph:
    global _KG
    if _KG is None:
        _KG = KnowledgeGraph()
        _KG.init()
        # Bind agents to the shared KG
        CARTOGRAPHER.kg = _KG
        from agents.oracle import ORACLE
        ORACLE.kg = _KG
        from agents.donna import DONNA
        DONNA.kg = _KG
    return _KG


def get_status() -> SystemStatus:
    return _STATUS


def _refresh_status(kg: KnowledgeGraph) -> None:
    _STATUS.pending_count = kg.pending_count()
    _STATUS.last_health_check = datetime.now()
    if _STATUS.pending_count > config.PENDING_AUTO_PAUSE_THRESHOLD:
        _STATUS.ingestion_paused = True


def _resolve_uploader_person_id(kg: KnowledgeGraph) -> str | None:
    """TUI ingest path uses admin = CEO. Find a Person whose telegram_chat_id
    matches `TELEGRAM_ADMIN_CHAT_ID`, falling back to the first Person with
    `role` containing ceo/founder. Returns None if no match — Document is then
    visible only via tier rules.
    """
    admin_chat = (config.TELEGRAM_ADMIN_CHAT_ID or "").strip()
    persons = kg.list_live("Person")
    if admin_chat:
        for p in persons:
            if (p["fields"].get("telegram_chat_id") or "") == admin_chat:
                return p["id"]
    for p in persons:
        role = (p["fields"].get("role") or "").lower()
        subs = " ".join(s.lower() for s in (p["fields"].get("sub_roles") or []))
        if any(k in role or k in subs for k in ("ceo", "founder")):
            return p["id"]
    return None


def ingest(source: str) -> AgentResult:
    """Run RAGNAR → CARTOGRAPHER. Source = file path or URL."""
    kg = get_kg()
    _refresh_status(kg)

    if _STATUS.ingestion_paused:
        return AgentResult(
            False,
            error=f"ingestion paused (pending={_STATUS.pending_count}). Triage in Pending screen.",
        )

    # 1. RAGNAR parses
    rag = RAGNAR.invoke({"source": source})
    if not rag.success:
        return rag
    raw_doc: RawDocument = rag.data
    log.info("pipeline_ragnar_ok", extra={"source": source, "chars": len(raw_doc.raw_text)})

    # 2. Create Document live node (always promoted)
    doc_staging = kg.stage_entity(
        entity_type="Document",
        fields={
            "title": raw_doc.metadata.get("filename", raw_doc.source),
            "type": raw_doc.format,
            "raw_path": raw_doc.source,
            "ingested_at": raw_doc.extracted_at.isoformat(),
        },
        doc_id=None,
        promotion_status="auto_eligible",
    )
    doc_live_id = kg.promote(
        doc_staging,
        f"Document: {raw_doc.metadata.get('filename', raw_doc.source)} ({raw_doc.format})",
        confirmed=True,  # user uploaded the doc; existence isn't disputed
    )
    # 2b. Resolve owner — TUI ingest = admin (CEO). Telegram ingest will pass
    # uploader_person_id in task later. Ownership-override (Phase 10C) lets the
    # owner see this doc regardless of tier gating.
    uploader_id = _resolve_uploader_person_id(kg)
    if uploader_id:
        kg.update_live_field(doc_live_id, "owner_id", uploader_id)
    log.info("pipeline_document_promoted",
             extra={"doc_id": doc_live_id, "owner_id": uploader_id})

    # 2a. 1-2 sentence plain-English summary (stored on Document.fields.summary)
    summary = ""
    try:
        summary = extractor.summarize(raw_doc.raw_text)
        if summary:
            kg.update_live_field(doc_live_id, "summary", summary)
    except Exception as e:
        log.warning("summary_failed", extra={"doc_id": doc_live_id, "error": str(e)})

    # 2a.bis SENTINEL — propose tier + doc_kind. Doc_kind also becomes a hint
    # passed to CARTOGRAPHER so the extractor can bias toward the right entities
    # (contract → parties+dates; meeting → people+decisions).
    sentinel_doc_kind: str | None = None
    try:
        from agents.sentinel import SENTINEL
        sent = SENTINEL.invoke({
            "title": raw_doc.metadata.get("filename", raw_doc.source),
            "text": raw_doc.raw_text,
            "kg": kg,
        })
        if sent.success:
            d = sent.data
            sentinel_doc_kind = d["doc_kind"]
            kg.update_live_field(doc_live_id, "doc_kind", d["doc_kind"])
            kg.update_live_field(doc_live_id, "tier", d["tier"])
            kg.update_live_field(doc_live_id, "tier_reason", d["reason"])
            log.info("pipeline_sentinel_tagged",
                     extra={"doc_id": doc_live_id, "tier": d["tier"],
                            "doc_kind": d["doc_kind"], "source": d["source"]})
    except Exception as e:
        log.warning("sentinel_failed", extra={"doc_id": doc_live_id, "error": str(e)})

    # 2b. Chunk + embed the full text for document chat (RAG)
    try:
        chunks = chunker.chunk_text(raw_doc.raw_text)
        if chunks:
            added = kg.add_chunks(
                doc_id=doc_live_id,
                doc_title=raw_doc.metadata.get("filename", raw_doc.source),
                chunks=chunks,
            )
            log.info("pipeline_chunks_added", extra={"doc_id": doc_live_id, "count": added})
    except Exception as e:
        log.warning("chunking_failed", extra={"doc_id": doc_live_id, "error": str(e)})

    # 3. CARTOGRAPHER extracts entities (with SENTINEL's doc_kind hint)
    cart = CARTOGRAPHER.invoke({
        "raw_doc": raw_doc,
        "doc_node_id": doc_live_id,
        "doc_kind": sentinel_doc_kind,
    })
    if not cart.success:
        return cart

    # 3a. SCRIBE — refresh personas of Persons connected to this Document.
    # Doc-mention is the strongest "your context changed" signal; rebuild
    # affected cards now so next chat reflects fresh facts.
    try:
        from agents.scribe import SCRIBE
        SCRIBE.kg = kg
        SCRIBE.invoke({"action": "refresh_for_doc", "doc_id": doc_live_id})
    except Exception as e:
        log.warning("scribe_refresh_failed",
                    extra={"doc_id": doc_live_id, "error": str(e)})

    # 4. Refresh status (pending count may have grown)
    _refresh_status(kg)

    cart_data = cart.data or {}
    cart_data["summary"] = summary
    cart_data["doc_title"] = raw_doc.metadata.get("filename", raw_doc.source)

    return AgentResult(
        True,
        data={
            "document_id": doc_live_id,
            "doc_title": cart_data.get("doc_title"),
            "summary": summary,
            "extraction_summary": cart_data,
            "system_status": {
                "pending": _STATUS.pending_count,
                "paused": _STATUS.ingestion_paused,
            },
        },
    )
