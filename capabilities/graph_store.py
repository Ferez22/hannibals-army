"""SQLite-backed graph store. Live + staging tables, indexed by (company_id, entity_type).

Schema versioning: bump SCHEMA_VERSION when changing tables. Current strategy is
wipe + reingest until Phase 4 (when alembic comes in).
"""
from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

log = logging.getLogger("hannibal.graph_store")

SCHEMA_VERSION = 1

# ---------------------------------------------------------------------------
# DDL
# ---------------------------------------------------------------------------
DDL = """
CREATE TABLE IF NOT EXISTS schema_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS live_nodes (
    id TEXT PRIMARY KEY,
    company_id TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    fields_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    last_verified_at TEXT NOT NULL,
    source_count INTEGER NOT NULL DEFAULT 0,
    confidence REAL NOT NULL DEFAULT 0.0
);
CREATE INDEX IF NOT EXISTS idx_live_nodes_company_type ON live_nodes(company_id, entity_type);

CREATE TABLE IF NOT EXISTS live_edges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id TEXT NOT NULL,
    from_id TEXT NOT NULL,
    type TEXT NOT NULL,
    to_id TEXT NOT NULL,
    properties_json TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (from_id) REFERENCES live_nodes(id),
    FOREIGN KEY (to_id) REFERENCES live_nodes(id)
);
CREATE INDEX IF NOT EXISTS idx_live_edges_from ON live_edges(company_id, from_id);
CREATE INDEX IF NOT EXISTS idx_live_edges_to   ON live_edges(company_id, to_id);
CREATE INDEX IF NOT EXISTS idx_live_edges_type ON live_edges(company_id, type);

CREATE TABLE IF NOT EXISTS staging_nodes (
    id TEXT PRIMARY KEY,
    company_id TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    fields_json TEXT NOT NULL,
    extracted_from_doc_id TEXT,
    extracted_at TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 0.0,
    promotion_status TEXT NOT NULL DEFAULT 'pending',
    blocked_reason TEXT,
    suggested_merge_into TEXT
);
CREATE INDEX IF NOT EXISTS idx_staging_status ON staging_nodes(company_id, promotion_status);
CREATE INDEX IF NOT EXISTS idx_staging_type   ON staging_nodes(company_id, entity_type);

CREATE TABLE IF NOT EXISTS staging_edges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id TEXT NOT NULL,
    from_ref TEXT NOT NULL,
    type TEXT NOT NULL,
    to_ref TEXT NOT NULL,
    properties_json TEXT,
    extracted_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS review_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    live_node_id TEXT,
    candidate_node_id TEXT,
    details_json TEXT,
    created_at TEXT NOT NULL,
    resolved INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS pending_blacklist (
    company_id TEXT NOT NULL,
    name_normalized TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    blacklisted_until TEXT NOT NULL,
    PRIMARY KEY (company_id, name_normalized, entity_type)
);
"""


# ---------------------------------------------------------------------------
class GraphStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    # ---- Connection ----
    @contextmanager
    def conn(self) -> Iterator[sqlite3.Connection]:
        c = sqlite3.connect(self.db_path)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys = ON")
        try:
            yield c
            c.commit()
        except Exception:
            c.rollback()
            raise
        finally:
            c.close()

    # ---- Schema ----
    def init_schema(self) -> None:
        with self.conn() as c:
            c.executescript(DDL)
            c.execute(
                "INSERT OR REPLACE INTO schema_meta(key, value) VALUES('version', ?)",
                (str(SCHEMA_VERSION),),
            )
        log.info("schema_initialized", extra={"version": SCHEMA_VERSION, "path": str(self.db_path)})

    # ---- Live nodes ----
    def insert_live_node(
        self,
        *,
        company_id: str,
        entity_type: str,
        fields: dict[str, Any],
        source_count: int = 1,
        confidence: float = 0.0,
        node_id: str | None = None,
    ) -> str:
        nid = node_id or f"{entity_type.lower()}_{uuid.uuid4().hex[:12]}"
        now = datetime.now().isoformat()
        with self.conn() as c:
            c.execute(
                """INSERT INTO live_nodes
                   (id, company_id, entity_type, fields_json, created_at, last_verified_at, source_count, confidence)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (nid, company_id, entity_type, json.dumps(fields), now, now, source_count, confidence),
            )
        return nid

    def get_live_node(self, node_id: str) -> dict | None:
        with self.conn() as c:
            row = c.execute("SELECT * FROM live_nodes WHERE id = ?", (node_id,)).fetchone()
            return _row_to_node(row) if row else None

    def list_live_nodes(self, company_id: str, entity_type: str | None = None) -> list[dict]:
        with self.conn() as c:
            if entity_type:
                rows = c.execute(
                    "SELECT * FROM live_nodes WHERE company_id = ? AND entity_type = ?",
                    (company_id, entity_type),
                ).fetchall()
            else:
                rows = c.execute(
                    "SELECT * FROM live_nodes WHERE company_id = ?", (company_id,)
                ).fetchall()
            return [_row_to_node(r) for r in rows]

    def bump_verification(self, node_id: str, new_source_count: int, new_confidence: float) -> None:
        now = datetime.now().isoformat()
        with self.conn() as c:
            c.execute(
                """UPDATE live_nodes
                   SET last_verified_at = ?, source_count = ?, confidence = ?
                   WHERE id = ?""",
                (now, new_source_count, new_confidence, node_id),
            )

    # ---- Live edges ----
    def insert_live_edge(
        self,
        *,
        company_id: str,
        from_id: str,
        type: str,
        to_id: str,
        properties: dict | None = None,
    ) -> int:
        now = datetime.now().isoformat()
        with self.conn() as c:
            cur = c.execute(
                """INSERT INTO live_edges (company_id, from_id, type, to_id, properties_json, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (company_id, from_id, type, to_id, json.dumps(properties) if properties else None, now),
            )
            return cur.lastrowid

    def edges_from(self, company_id: str, from_id: str) -> list[dict]:
        with self.conn() as c:
            rows = c.execute(
                "SELECT * FROM live_edges WHERE company_id = ? AND from_id = ?",
                (company_id, from_id),
            ).fetchall()
            return [_row_to_edge(r) for r in rows]

    def edges_to(self, company_id: str, to_id: str) -> list[dict]:
        with self.conn() as c:
            rows = c.execute(
                "SELECT * FROM live_edges WHERE company_id = ? AND to_id = ?",
                (company_id, to_id),
            ).fetchall()
            return [_row_to_edge(r) for r in rows]

    def neighbors(self, company_id: str, node_id: str) -> list[dict]:
        """All edges where node is either endpoint."""
        return self.edges_from(company_id, node_id) + self.edges_to(company_id, node_id)

    # ---- Staging ----
    def insert_staging_node(
        self,
        *,
        company_id: str,
        entity_type: str,
        fields: dict[str, Any],
        extracted_from_doc_id: str | None,
        promotion_status: str = "pending",
        blocked_reason: str | None = None,
        suggested_merge_into: str | None = None,
        confidence: float = 0.0,
    ) -> str:
        nid = f"s_{entity_type.lower()}_{uuid.uuid4().hex[:12]}"
        now = datetime.now().isoformat()
        with self.conn() as c:
            c.execute(
                """INSERT INTO staging_nodes
                   (id, company_id, entity_type, fields_json, extracted_from_doc_id,
                    extracted_at, confidence, promotion_status, blocked_reason, suggested_merge_into)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    nid, company_id, entity_type, json.dumps(fields),
                    extracted_from_doc_id, now, confidence,
                    promotion_status, blocked_reason, suggested_merge_into,
                ),
            )
        return nid

    def list_staging_nodes(
        self, company_id: str, status: str | None = None
    ) -> list[dict]:
        with self.conn() as c:
            if status:
                rows = c.execute(
                    "SELECT * FROM staging_nodes WHERE company_id = ? AND promotion_status = ?",
                    (company_id, status),
                ).fetchall()
            else:
                rows = c.execute(
                    "SELECT * FROM staging_nodes WHERE company_id = ?", (company_id,)
                ).fetchall()
            return [_row_to_staging(r) for r in rows]

    def pending_count(self, company_id: str) -> int:
        with self.conn() as c:
            row = c.execute(
                "SELECT COUNT(*) FROM staging_nodes WHERE company_id = ? AND promotion_status = 'pending'",
                (company_id,),
            ).fetchone()
            return row[0]

    def insert_staging_edge(
        self,
        *,
        company_id: str,
        from_ref: str,
        type: str,
        to_ref: str,
        properties: dict | None = None,
    ) -> int:
        now = datetime.now().isoformat()
        with self.conn() as c:
            cur = c.execute(
                """INSERT INTO staging_edges (company_id, from_ref, type, to_ref, properties_json, extracted_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (company_id, from_ref, type, to_ref, json.dumps(properties) if properties else None, now),
            )
            return cur.lastrowid

    # ---- Promotion ----
    def promote_staging(self, staging_id: str) -> str:
        """Move staging_nodes row to live_nodes. Returns live node id."""
        with self.conn() as c:
            row = c.execute(
                "SELECT * FROM staging_nodes WHERE id = ?", (staging_id,)
            ).fetchone()
            if not row:
                raise ValueError(f"staging node {staging_id} not found")

            entity_type = row["entity_type"]
            live_id = f"{entity_type.lower()}_{uuid.uuid4().hex[:12]}"
            now = datetime.now().isoformat()
            # Initial confidence per formula: min(1, source_count/3). source_count starts at 1.
            initial_confidence = min(1.0, 1.0 / 3.0)

            c.execute(
                """INSERT INTO live_nodes
                   (id, company_id, entity_type, fields_json, created_at, last_verified_at, source_count, confidence)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    live_id, row["company_id"], entity_type, row["fields_json"],
                    now, now, 1, initial_confidence,
                ),
            )
            # mark staging as promoted (keep row for audit)
            c.execute(
                "UPDATE staging_nodes SET promotion_status = 'promoted', suggested_merge_into = ? WHERE id = ?",
                (live_id, staging_id),
            )
        log.info("promoted", extra={"staging_id": staging_id, "live_id": live_id})
        return live_id

    # ---- Review queue ----
    def delete_live_edge(self, edge_id: int) -> int:
        with self.conn() as c:
            cur = c.execute("DELETE FROM live_edges WHERE id = ?", (edge_id,))
            return cur.rowcount

    def find_edges(
        self, company_id: str, from_id: str, type: str, to_id: str
    ) -> list[dict]:
        with self.conn() as c:
            rows = c.execute(
                """SELECT * FROM live_edges
                   WHERE company_id = ? AND from_id = ? AND type = ? AND to_id = ?""",
                (company_id, from_id, type, to_id),
            ).fetchall()
            return [_row_to_edge(r) for r in rows]

    def delete_live_node(self, company_id: str, node_id: str) -> dict:
        """Delete node + all its edges. Returns {edges_removed, node_removed}."""
        with self.conn() as c:
            removed_edges = c.execute(
                "DELETE FROM live_edges WHERE company_id = ? AND (from_id = ? OR to_id = ?)",
                (company_id, node_id, node_id),
            ).rowcount
            removed_node = c.execute(
                "DELETE FROM live_nodes WHERE id = ?", (node_id,)
            ).rowcount
        return {"edges_removed": removed_edges, "node_removed": removed_node}

    def list_review_queue(
        self, company_id: str, kind: str | None = None, resolved: bool = False
    ) -> list[dict]:
        with self.conn() as c:
            q = "SELECT * FROM review_queue WHERE company_id = ? AND resolved = ?"
            params: list = [company_id, 1 if resolved else 0]
            if kind:
                q += " AND kind = ?"
                params.append(kind)
            q += " ORDER BY created_at DESC"
            rows = c.execute(q, params).fetchall()
            return [_row_to_review(r) for r in rows]

    def resolve_review(self, review_id: int) -> None:
        with self.conn() as c:
            c.execute(
                "UPDATE review_queue SET resolved = 1 WHERE id = ?", (review_id,)
            )

    def queue_for_review(
        self,
        *,
        company_id: str,
        kind: str,
        entity_type: str,
        live_node_id: str | None,
        candidate_node_id: str | None,
        details: dict | None = None,
    ) -> int:
        now = datetime.now().isoformat()
        with self.conn() as c:
            cur = c.execute(
                """INSERT INTO review_queue
                   (company_id, kind, entity_type, live_node_id, candidate_node_id, details_json, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (company_id, kind, entity_type, live_node_id, candidate_node_id,
                 json.dumps(details) if details else None, now),
            )
            return cur.lastrowid


# ---------------------------------------------------------------------------
def _row_to_node(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "company_id": row["company_id"],
        "entity_type": row["entity_type"],
        "fields": json.loads(row["fields_json"]),
        "created_at": row["created_at"],
        "last_verified_at": row["last_verified_at"],
        "source_count": row["source_count"],
        "confidence": row["confidence"],
    }


def _row_to_edge(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "from_id": row["from_id"],
        "type": row["type"],
        "to_id": row["to_id"],
        "properties": json.loads(row["properties_json"]) if row["properties_json"] else {},
        "created_at": row["created_at"],
    }


def _row_to_review(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "company_id": row["company_id"],
        "kind": row["kind"],
        "entity_type": row["entity_type"],
        "live_node_id": row["live_node_id"],
        "candidate_node_id": row["candidate_node_id"],
        "details": json.loads(row["details_json"]) if row["details_json"] else {},
        "created_at": row["created_at"],
        "resolved": bool(row["resolved"]),
    }


def _row_to_staging(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "company_id": row["company_id"],
        "entity_type": row["entity_type"],
        "fields": json.loads(row["fields_json"]),
        "extracted_from_doc_id": row["extracted_from_doc_id"],
        "extracted_at": row["extracted_at"],
        "confidence": row["confidence"],
        "promotion_status": row["promotion_status"],
        "blocked_reason": row["blocked_reason"],
        "suggested_merge_into": row["suggested_merge_into"],
    }
