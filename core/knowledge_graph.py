"""KnowledgeGraph — facade over graph + vector stores.

Phase 0 stub. Wiring lands in Phase 2.
"""
from __future__ import annotations

from pathlib import Path

from capabilities.graph_store import GraphStore
from capabilities.vector_store import VectorStore


class KnowledgeGraph:
    """Single entry point for all graph + vector operations.

    Exposes `live` and `staging` namespaces separately so callers
    cannot accidentally write untrusted data to the live graph.
    """

    def __init__(self, db_path: Path, vector_dir: Path) -> None:
        self.graph = GraphStore(db_path)
        self.vectors = VectorStore(vector_dir)

    def init(self) -> None:
        raise NotImplementedError("Phase 2")
