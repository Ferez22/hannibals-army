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
    return _KG


def get_status() -> SystemStatus:
    return _STATUS


def _refresh_status(kg: KnowledgeGraph) -> None:
    _STATUS.pending_count = kg.pending_count()
    _STATUS.last_health_check = datetime.now()
    if _STATUS.pending_count > config.PENDING_AUTO_PAUSE_THRESHOLD:
        _STATUS.ingestion_paused = True


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
    )
    log.info("pipeline_document_promoted", extra={"doc_id": doc_live_id})

    # 3. CARTOGRAPHER extracts entities
    cart = CARTOGRAPHER.invoke({"raw_doc": raw_doc, "doc_node_id": doc_live_id})
    if not cart.success:
        return cart

    # 4. Refresh status (pending count may have grown)
    _refresh_status(kg)

    return AgentResult(
        True,
        data={
            "document_id": doc_live_id,
            "extraction_summary": cart.data,
            "system_status": {
                "pending": _STATUS.pending_count,
                "paused": _STATUS.ingestion_paused,
            },
        },
    )
