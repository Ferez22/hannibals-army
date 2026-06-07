"""Hybrid retrieval — BM25 lexical + dense cosine, fused via Reciprocal Rank Fusion.

BM25 catches exact-keyword matches dense embeddings miss (e.g., "wordpress",
"domiciliated", proper nouns, IDs). Dense catches semantic similarity. RRF
combines them without parameter tuning.

The BM25 index is rebuilt from SQL on every search — cheap at MVP scale
(<100k chunks). When chunks grow, persist BM25 index to disk.
"""
from __future__ import annotations

import logging
import re
from typing import Any

import config

log = logging.getLogger("hannibal.retriever")

# RRF constant — k=60 is the classic value from Cormack et al. 2009
RRF_K = 60


def hybrid_search_chunks(
    kg,
    query: str,
    k: int = 5,
    candidates_per_source: int = 20,
    sender_tier_rank: int | None = None,
    sender_person_id: str | None = None,
) -> list[dict[str, Any]]:
    """Return top-k chunks by RRF-fused BM25 + dense ranking.

    Each chunk dict: {chunk_id, text, doc_id, doc_title, ordinal, score_bm25, score_dense, score_rrf}

    If sender_tier_rank is set, filter chunks by doc tier:
    `tier_rank(doc.tier) <= sender_tier_rank OR doc.owner_id == sender_person_id`.
    """
    # 1. Dense top-N from Chroma
    dense_hits = kg.search_chunks(query, k=candidates_per_source)

    # 2. BM25 top-N from SQL
    bm25_hits = _bm25_search(kg, query, k=candidates_per_source)

    # 3. RRF fusion — combine ranks from both sources
    fused = _rrf_fuse([dense_hits, bm25_hits], score_keys=["distance", "score_bm25"])

    # 4. Tier filter (Phase 10A)
    if sender_tier_rank is not None:
        fused = _tier_filter(kg, fused, sender_tier_rank, sender_person_id)

    return fused[:k]


def _tier_filter(
    kg,
    chunks: list[dict[str, Any]],
    sender_tier_rank: int,
    sender_person_id: str | None,
) -> list[dict[str, Any]]:
    """Drop chunks from docs the sender cannot see.

    Rule: keep if doc tier_rank <= sender_tier_rank OR sender owns the doc.
    Unconfirmed-tier docs are visible only to CEO (rank 0) and owner.
    """
    import json

    doc_ids = list({c["doc_id"] for c in chunks if c.get("doc_id")})
    if not doc_ids:
        return chunks

    placeholders = ",".join("?" * len(doc_ids))
    with kg.graph.conn() as c:
        rows = c.execute(
            f"SELECT id, fields_json FROM live_nodes WHERE id IN ({placeholders})",
            doc_ids,
        ).fetchall()

    doc_meta: dict[str, dict] = {}
    for r in rows:
        try:
            fields = json.loads(r["fields_json"] or "{}")
        except Exception:
            fields = {}
        doc_meta[r["id"]] = fields

    kept: list[dict[str, Any]] = []
    for ch in chunks:
        meta = doc_meta.get(ch["doc_id"], {})
        doc_tier = meta.get("tier") or config.DEFAULT_DOC_TIER
        owner_id = meta.get("owner_id")
        tier_confirmed = bool(meta.get("tier_confirmed_by"))
        doc_rank = config.tier_rank(doc_tier)
        # Unconfirmed docs: only CEO (rank 0) + owner see them
        if not tier_confirmed:
            if sender_tier_rank == 0 or owner_id == sender_person_id:
                kept.append(ch)
            continue
        # Confirmed: sender rank must reach doc's required tier (lower rank = more access)
        if sender_tier_rank <= doc_rank or owner_id == sender_person_id:
            kept.append(ch)
    return kept


# ---------------------------------------------------------------------------
def _bm25_search(kg, query: str, k: int) -> list[dict[str, Any]]:
    from rank_bm25 import BM25Okapi

    # Pull all chunks for this company. Cheap until ~50k chunks.
    with kg.graph.conn() as c:
        rows = c.execute(
            """SELECT c.id, c.doc_id, c.ordinal, c.text, ln.fields_json
               FROM document_chunks c
               LEFT JOIN live_nodes ln ON ln.id = c.doc_id
               WHERE c.company_id = ?""",
            (kg.company_id,),
        ).fetchall()
    if not rows:
        return []

    chunks = []
    import json
    for r in rows:
        doc_title = ""
        if r["fields_json"]:
            try:
                doc_title = json.loads(r["fields_json"]).get("title", "")
            except Exception:
                pass
        chunks.append({
            "chunk_id": r["id"],
            "doc_id": r["doc_id"],
            "doc_title": doc_title,
            "ordinal": r["ordinal"],
            "text": r["text"],
        })

    tokenized_corpus = [_tokenize(c["text"]) for c in chunks]
    bm25 = BM25Okapi(tokenized_corpus)
    scores = bm25.get_scores(_tokenize(query))

    # Rank by score desc, take top-k
    ranked = sorted(zip(chunks, scores), key=lambda x: x[1], reverse=True)
    hits = []
    for ch, sc in ranked[:k]:
        if sc <= 0:
            break
        hits.append({**ch, "score_bm25": float(sc)})
    return hits


_TOKEN_RE = re.compile(r"[A-Za-zÀ-ÿ0-9_]+", re.UNICODE)


def _tokenize(text: str) -> list[str]:
    if not text:
        return []
    return [t.lower() for t in _TOKEN_RE.findall(text)]


# ---------------------------------------------------------------------------
def _rrf_fuse(
    rankings: list[list[dict[str, Any]]],
    score_keys: list[str],
    k: int = RRF_K,
) -> list[dict[str, Any]]:
    """Reciprocal Rank Fusion. Returns merged list sorted by combined score.

    rankings: list of result lists (each pre-sorted by their own metric)
    score_keys: name of original score field per ranking (for diagnostics)
    Returns each dict augmented with `score_rrf`.
    """
    fused: dict[str, dict[str, Any]] = {}
    for ranking_idx, ranking in enumerate(rankings):
        score_key = score_keys[ranking_idx]
        for rank, item in enumerate(ranking, start=1):
            cid = item["chunk_id"]
            if cid not in fused:
                fused[cid] = dict(item)
                fused[cid]["score_rrf"] = 0.0
            fused[cid]["score_rrf"] += 1.0 / (k + rank)
            fused[cid][score_key] = item.get(score_key)

    return sorted(fused.values(), key=lambda x: x["score_rrf"], reverse=True)
