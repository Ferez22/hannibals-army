"""Tier correction memory — SENTINEL learning loop.

Persistent SQLite store of every tier confirmation (silent agreement + explicit
override). Used for two things:

  1) Few-shot recall — SENTINEL fetches top-K nearest past corrections by
     cosine similarity over title+excerpt embeddings, injects them as examples
     in the LLM prompt.

  2) Rule mining (deferred to 10B.9) — periodic job that aggregates
     overrides and proposes new RULE_SIGNALS to CARTOGRAPHER/SENTINEL.

Embeddings are computed lazily at write time using the same
sentence-transformers model the vector store uses. Stored as raw float32
BLOB. Brute-force cosine at lookup time — fine until ~10k corrections.
"""
from __future__ import annotations

import array
import logging
import math
from datetime import datetime
from typing import Any

import config

log = logging.getLogger("hannibal.tier_memory")

EXCERPT_MAX_CHARS = 500
TOPK_FEWSHOT = 5
MIN_COSINE = 0.35  # below this, treat as not similar enough to include


# ---------------------------------------------------------------------------
# Embedding helpers
# ---------------------------------------------------------------------------
_EMBEDDER: Any = None


def _embedder() -> Any:
    global _EMBEDDER
    if _EMBEDDER is None:
        from sentence_transformers import SentenceTransformer
        _EMBEDDER = SentenceTransformer(config.EMBEDDING_MODEL)
    return _EMBEDDER


def _embed(text: str) -> bytes:
    vec = _embedder().encode([text or ""], convert_to_numpy=True)[0]
    return array.array("f", vec.tolist()).tobytes()


def _decode(blob: bytes | None) -> list[float] | None:
    if not blob:
        return None
    arr = array.array("f")
    arr.frombytes(blob)
    return list(arr)


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------
def record_correction(
    *,
    kg,
    doc_id: str | None,
    doc_title: str,
    doc_text: str,
    sentinel: dict[str, Any] | None,
    ceo_kind: str | None,
    ceo_tier: str,
    ceo_reason: str | None,
    override_by: str | None,
) -> int:
    """Insert a correction row. Returns the inserted row id."""
    excerpt = (doc_text or "")[:EXCERPT_MAX_CHARS]
    embed_text = f"{doc_title}\n{excerpt}"
    blob = _embed(embed_text)
    sentinel = sentinel or {}
    s_tier = sentinel.get("tier")
    is_override = 1 if (s_tier is not None and s_tier != ceo_tier) else 0
    now = datetime.now().isoformat()

    with kg.graph.conn() as c:
        cur = c.execute(
            """INSERT INTO tier_corrections
               (company_id, doc_id, doc_title, doc_excerpt, embedding,
                sentinel_kind, sentinel_tier, sentinel_reason, sentinel_source,
                ceo_kind, ceo_tier, ceo_reason,
                is_override, override_at, override_by)
               VALUES (?, ?, ?, ?, ?,
                       ?, ?, ?, ?,
                       ?, ?, ?,
                       ?, ?, ?)""",
            (
                kg.company_id, doc_id, doc_title, excerpt, blob,
                sentinel.get("doc_kind"), s_tier, sentinel.get("reason"), sentinel.get("source"),
                ceo_kind, ceo_tier, ceo_reason,
                is_override, now, override_by,
            ),
        )
        row_id = cur.lastrowid
    log.info(
        "tier_correction_recorded",
        extra={
            "id": row_id, "doc_id": doc_id, "is_override": bool(is_override),
            "ceo_tier": ceo_tier, "sentinel_tier": s_tier,
        },
    )
    return row_id


# ---------------------------------------------------------------------------
# Read — few-shot recall
# ---------------------------------------------------------------------------
def nearest_corrections(
    *,
    kg,
    title: str,
    text: str,
    k: int = TOPK_FEWSHOT,
    overrides_only: bool = False,
) -> list[dict[str, Any]]:
    """Return up to k nearest past corrections by cosine similarity.

    If `overrides_only` is True, restrict to rows where CEO disagreed with SENTINEL
    (these are the strongest learning signal).
    """
    query_vec = _decode(_embed(f"{(title or '')}\n{(text or '')[:EXCERPT_MAX_CHARS]}"))
    if not query_vec:
        return []
    with kg.graph.conn() as c:
        sql = """SELECT id, doc_title, doc_excerpt, embedding,
                        sentinel_tier, sentinel_kind, sentinel_reason,
                        ceo_tier, ceo_kind, ceo_reason,
                        is_override, override_at
                 FROM tier_corrections
                 WHERE company_id = ?"""
        params: tuple = (kg.company_id,)
        if overrides_only:
            sql += " AND is_override = 1"
        rows = c.execute(sql, params).fetchall()
    scored: list[tuple[float, dict[str, Any]]] = []
    for r in rows:
        vec = _decode(r["embedding"])
        if not vec:
            continue
        sim = _cosine(query_vec, vec)
        if sim < MIN_COSINE:
            continue
        scored.append((sim, dict(r)))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [{"similarity": round(s, 3), **r} for s, r in scored[:k]]


def correction_count(*, kg, overrides_only: bool = False) -> int:
    with kg.graph.conn() as c:
        sql = "SELECT COUNT(*) AS n FROM tier_corrections WHERE company_id = ?"
        if overrides_only:
            sql += " AND is_override = 1"
        row = c.execute(sql, (kg.company_id,)).fetchone()
    return int(row["n"]) if row else 0


# ---------------------------------------------------------------------------
# Rule-mining stub (Phase 10B.9 — surfaced via CLI / future TUI screen)
# ---------------------------------------------------------------------------
MIN_SUPPORT = 3  # minimum overrides with same target tier before proposing a rule


def mine_rule_candidates(*, kg) -> list[dict[str, Any]]:
    """Aggregate overrides → propose rule candidates.

    Crude v1: group overrides by ceo_tier; for each group, find the most common
    bigram/trigram in titles. If support >= MIN_SUPPORT, emit a candidate the
    CEO can confirm into RULE_SIGNALS.

    Output shape:
      [{"target_tier": "c_level", "phrase": "headcount plan",
        "support": 4, "examples": [{title, ceo_reason}, ...]}]

    Confirmation is manual for now (no auto-write to RULE_SIGNALS).
    """
    from collections import Counter

    with kg.graph.conn() as c:
        rows = c.execute(
            """SELECT doc_title, ceo_tier, ceo_kind, ceo_reason
               FROM tier_corrections
               WHERE company_id = ? AND is_override = 1""",
            (kg.company_id,),
        ).fetchall()
    if not rows:
        return []

    by_tier: dict[str, list[dict]] = {}
    for r in rows:
        by_tier.setdefault(r["ceo_tier"], []).append(dict(r))

    candidates: list[dict[str, Any]] = []
    for tier, group in by_tier.items():
        if len(group) < MIN_SUPPORT:
            continue
        # n-gram count over titles (lowercased)
        ngrams: Counter[str] = Counter()
        for ex in group:
            title = (ex["doc_title"] or "").lower()
            tokens = [t for t in title.split() if len(t) > 2]
            for n in (2, 3):
                for i in range(len(tokens) - n + 1):
                    ngrams[" ".join(tokens[i:i + n])] += 1
        for phrase, support in ngrams.most_common(5):
            if support >= MIN_SUPPORT:
                candidates.append({
                    "target_tier": tier,
                    "phrase": phrase,
                    "support": support,
                    "examples": group[:5],
                })
    return candidates
