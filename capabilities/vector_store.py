"""Chroma-backed vector store. Only live nodes are embedded.

Uses multilingual MiniLM (DE/FR/EN/AR — fits QartMina's doc mix).
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import config

log = logging.getLogger("hannibal.vector_store")


class VectorStore:
    def __init__(self, persist_dir: Path) -> None:
        self.persist_dir = persist_dir
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        self._client = None
        self._collection = None

    def init(self) -> None:
        import chromadb
        from chromadb.utils import embedding_functions

        self._client = chromadb.PersistentClient(path=str(self.persist_dir))
        embed_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name=config.EMBEDDING_MODEL
        )
        self._collection = self._client.get_or_create_collection(
            name="live_nodes",
            embedding_function=embed_fn,
            metadata={"hnsw:space": "cosine"},
        )
        self._chunks = self._client.get_or_create_collection(
            name="doc_chunks",
            embedding_function=embed_fn,
            metadata={"hnsw:space": "cosine"},
        )
        log.info("vector_store_initialized", extra={"path": str(self.persist_dir)})

    def add(
        self,
        *,
        node_id: str,
        description: str,
        company_id: str,
        entity_type: str,
    ) -> None:
        if self._collection is None:
            raise RuntimeError("VectorStore not initialized")
        self._collection.upsert(
            ids=[node_id],
            documents=[description],
            metadatas=[{"company_id": company_id, "entity_type": entity_type}],
        )

    def search(
        self,
        *,
        query: str,
        company_id: str,
        k: int = 5,
        entity_type: str | None = None,
    ) -> list[dict[str, Any]]:
        if self._collection is None:
            raise RuntimeError("VectorStore not initialized")
        where = {"company_id": company_id}
        if entity_type:
            where = {"$and": [{"company_id": company_id}, {"entity_type": entity_type}]}
        if self._collection.count() == 0:
            return []
        result = self._collection.query(
            query_texts=[query],
            n_results=k,
            where=where,
        )
        ids = (result.get("ids") or [[]])[0]
        docs = (result.get("documents") or [[]])[0]
        dists = (result.get("distances") or [[]])[0]
        hits: list[dict[str, Any]] = []
        for nid, doc, dist in zip(ids, docs, dists):
            hits.append({"node_id": nid, "document": doc, "distance": dist})
        return hits

    def delete(self, node_id: str) -> None:
        if self._collection is None:
            raise RuntimeError("VectorStore not initialized")
        self._collection.delete(ids=[node_id])

    def count(self) -> int:
        if self._collection is None:
            return 0
        return self._collection.count()

    # ---- Chunk operations ----
    def add_chunk(
        self,
        *,
        chunk_id: str,
        text: str,
        company_id: str,
        doc_id: str,
        doc_title: str,
        ordinal: int,
    ) -> None:
        if self._chunks is None:
            raise RuntimeError("VectorStore not initialized")
        self._chunks.upsert(
            ids=[chunk_id],
            documents=[text],
            metadatas=[{
                "company_id": company_id,
                "doc_id": doc_id,
                "doc_title": doc_title,
                "ordinal": ordinal,
            }],
        )

    def search_chunks(
        self,
        *,
        query: str,
        company_id: str,
        k: int = 5,
    ) -> list[dict[str, Any]]:
        if self._chunks is None:
            raise RuntimeError("VectorStore not initialized")
        if self._chunks.count() == 0:
            return []
        result = self._chunks.query(
            query_texts=[query],
            n_results=k,
            where={"company_id": company_id},
        )
        ids = (result.get("ids") or [[]])[0]
        docs = (result.get("documents") or [[]])[0]
        dists = (result.get("distances") or [[]])[0]
        metas = (result.get("metadatas") or [[]])[0]
        hits: list[dict[str, Any]] = []
        for cid, doc, dist, meta in zip(ids, docs, dists, metas):
            hits.append({
                "chunk_id": cid,
                "text": doc,
                "distance": dist,
                "doc_id": meta.get("doc_id"),
                "doc_title": meta.get("doc_title"),
                "ordinal": meta.get("ordinal"),
            })
        return hits

    def delete_chunks_for_doc(self, doc_id: str) -> None:
        if self._chunks is None:
            return
        self._chunks.delete(where={"doc_id": doc_id})

    def chunk_count(self) -> int:
        return self._chunks.count() if self._chunks is not None else 0
