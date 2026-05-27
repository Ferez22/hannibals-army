"""KnowledgeGraph — facade over GraphStore + VectorStore.

Exposes `live` and `staging` namespaces so callers can't accidentally
write untrusted data to the live graph.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import config
from capabilities.graph_store import GraphStore
from capabilities.vector_store import VectorStore

log = logging.getLogger("hannibal.kg")


class KnowledgeGraph:
    def __init__(self, db_path: Path | None = None, vector_dir: Path | None = None) -> None:
        self.graph = GraphStore(db_path or config.DB_PATH)
        self.vectors = VectorStore(vector_dir or config.VECTOR_DIR)
        self.company_id = config.COMPANY_ID
        self._initialized = False

    def init(self) -> None:
        if self._initialized:
            return
        self.graph.init_schema()
        self.vectors.init()
        self._initialized = True
        log.info("kg_initialized")

    # ---- Live operations (read-only for most callers) ----
    def list_live(self, entity_type: str | None = None) -> list[dict]:
        return self.graph.list_live_nodes(self.company_id, entity_type)

    def get_live(self, node_id: str) -> dict | None:
        return self.graph.get_live_node(node_id)

    def neighbors(self, node_id: str) -> list[dict]:
        return self.graph.neighbors(self.company_id, node_id)

    def search(self, query: str, k: int = 5, entity_type: str | None = None) -> list[dict]:
        return self.vectors.search(
            query=query, company_id=self.company_id, k=k, entity_type=entity_type
        )

    # ---- Write operations — go through staging ----
    def stage_entity(
        self,
        *,
        entity_type: str,
        fields: dict[str, Any],
        doc_id: str | None,
        promotion_status: str = "pending",
        blocked_reason: str | None = None,
        suggested_merge_into: str | None = None,
    ) -> str:
        return self.graph.insert_staging_node(
            company_id=self.company_id,
            entity_type=entity_type,
            fields=fields,
            extracted_from_doc_id=doc_id,
            promotion_status=promotion_status,
            blocked_reason=blocked_reason,
            suggested_merge_into=suggested_merge_into,
        )

    def stage_edge(
        self, *, from_ref: str, type: str, to_ref: str, properties: dict | None = None
    ) -> int:
        return self.graph.insert_staging_edge(
            company_id=self.company_id,
            from_ref=from_ref,
            type=type,
            to_ref=to_ref,
            properties=properties,
        )

    def promote(self, staging_id: str, description: str) -> str:
        """Promote staging node → live, embed description in vector store."""
        live_id = self.graph.promote_staging(staging_id)
        node = self.graph.get_live_node(live_id)
        if node:
            self.vectors.add(
                node_id=live_id,
                description=description,
                company_id=self.company_id,
                entity_type=node["entity_type"],
            )
        return live_id

    def bump_corroboration(self, live_id: str) -> None:
        """Increment source_count, recompute confidence."""
        node = self.graph.get_live_node(live_id)
        if not node:
            return
        new_count = node["source_count"] + 1
        new_confidence = min(1.0, new_count / 3.0)
        self.graph.bump_verification(live_id, new_count, new_confidence)

    def add_live_edge(
        self, *, from_id: str, type: str, to_id: str, properties: dict | None = None
    ) -> int:
        return self.graph.insert_live_edge(
            company_id=self.company_id,
            from_id=from_id,
            type=type,
            to_id=to_id,
            properties=properties,
        )

    def pending_count(self) -> int:
        return self.graph.pending_count(self.company_id)

    def list_pending(self) -> list[dict]:
        return self.graph.list_staging_nodes(self.company_id, "pending")
