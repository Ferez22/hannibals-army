"""Chroma-backed vector store. Phase 0 stub — wiring lands in Phase 2."""
from __future__ import annotations

from pathlib import Path


class VectorStore:
    """Wraps Chroma. Only live nodes are embedded.

    Phase 2 implements:
      - init with paraphrase-multilingual-MiniLM-L12-v2
      - add(node_id, description, metadata)
      - search(query, k) → list of node_ids with similarity scores
    """

    def __init__(self, persist_dir: Path) -> None:
        self.persist_dir = persist_dir

    def init(self) -> None:
        raise NotImplementedError("Phase 2")

    def add(self, *args, **kwargs):
        raise NotImplementedError("Phase 2")

    def search(self, *args, **kwargs):
        raise NotImplementedError("Phase 2")
