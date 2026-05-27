"""SQLite-backed graph store. Phase 0 stub — schema and CRUD land in Phase 2."""
from __future__ import annotations

from pathlib import Path


class GraphStore:
    """Wraps SQLite for live + staging nodes and edges.

    Phase 2 implements:
      - schema (live_nodes, live_edges, staging_nodes, staging_edges, review_queue)
      - CRUD with company_id scoping
      - recursive CTE traversal for CHILD_OF hierarchies
    """

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path

    def init_schema(self) -> None:
        raise NotImplementedError("Phase 2")

    def insert_staging_node(self, *args, **kwargs):
        raise NotImplementedError("Phase 2")

    def promote(self, staging_id: str) -> str:
        raise NotImplementedError("Phase 2")

    def query_live(self, *args, **kwargs):
        raise NotImplementedError("Phase 2")
