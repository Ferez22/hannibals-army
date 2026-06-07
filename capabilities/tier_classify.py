"""SENTINEL helper — classify a document's kind + deduce a default tier.

Three-stage pipeline:
  1) Rule-based signal scan over raw text (fast, deterministic, no LLM)
  2) LLM fallback that returns {doc_kind, tier, reason, confidence};
     when `kg` is provided, top-K nearest past corrections are pulled from
     `capabilities/tier_memory.py` and injected as few-shot examples.
  3) Conservative `director` default if both fail.

Output schema (always populated, even on LLM failure):
  {
    "doc_kind":   one of DocKind | None,
    "tier":       one of TIERS (defaults to DEFAULT_DOC_TIER),
    "reason":     short string,
    "confidence": float in [0, 1],
    "source":     "rules" | "llm" | "fallback",
  }

Caller (`agents/sentinel.py`) is responsible for attaching this to the staged
Document and surfacing it in the Pending screen for admin confirmation.
"""
from __future__ import annotations

import logging
import re
from typing import Any

import config
from capabilities import llm

log = logging.getLogger("hannibal.sentinel")

# ---------------------------------------------------------------------------
# Rule signals — high-confidence keyword triggers
# ---------------------------------------------------------------------------
# Each entry: (regex, doc_kind, tier, reason)
RULE_SIGNALS: list[tuple[re.Pattern[str], str, str, str]] = [
    # Board / shareholders → c_level
    (re.compile(r"\b(board of directors|shareholders?|board meeting|board resolution)\b", re.I),
     "contract", "c_level", "board/shareholder mention"),
    (re.compile(r"\b(equity grant|stock option|cap table|409a|valuation)\b", re.I),
     "private", "c_level", "equity/valuation mention"),
    # Comp / HR private → c_level
    (re.compile(r"\b(salary|compensation|payslip|bonus|severance)\b", re.I),
     "private", "c_level", "compensation data"),
    (re.compile(r"\b(performance review|disciplinary|termination letter|warning letter|grievance)\b", re.I),
     "private", "c_level", "HR private matter"),
    # Financial reports → c_level
    (re.compile(r"\b(p&l|profit\s*&\s*loss|income statement|balance sheet|cash flow statement|financial statement)\b", re.I),
     "report", "c_level", "financial statement"),
    # Legal / contracts (default director)
    (re.compile(r"\b(non[-\s]?disclosure agreement|nda|confidentiality agreement)\b", re.I),
     "contract", "director", "NDA"),
    (re.compile(r"\b(master services agreement|msa|statement of work|sow|service agreement)\b", re.I),
     "contract", "director", "MSA / SOW"),
    (re.compile(r"\b(this agreement|the parties agree|hereby agrees|whereas)\b", re.I),
     "contract", "director", "contract boilerplate"),
    # All-hands / public → everyone
    (re.compile(r"\b(all[-\s]?hands|town hall|company[-\s]?wide|handbook|code of conduct)\b", re.I),
     "policy", "everyone", "company-wide audience"),
    (re.compile(r"\b(welcome to|onboarding|employee handbook)\b", re.I),
     "policy", "everyone", "onboarding/handbook"),
    # Presentations → keyword-dependent
    (re.compile(r"\b(quarterly review|qbr|board deck|investor deck|investor update)\b", re.I),
     "presentation", "c_level", "investor / board deck"),
    (re.compile(r"\b(roadmap|product strategy|dept (review|update))\b", re.I),
     "presentation", "director", "internal strategy deck"),
]


# doc_kind → default tier if no rule fires
KIND_DEFAULT_TIER: dict[str, str] = {
    "contract":     "director",
    "private":      "c_level",
    "report":       "director",
    "presentation": "director",
    "policy":       "everyone",
    "general":      "director",
}


# ---------------------------------------------------------------------------
def classify(*, title: str, text: str, kg=None) -> dict[str, Any]:
    """Classify a document. Always returns a populated dict — never raises.

    If `kg` is provided, few-shot examples are pulled from `tier_corrections`
    via `tier_memory.nearest_corrections` and injected into the LLM prompt.
    """
    text = (text or "")[:8000]  # cap for LLM prompt budget
    title = (title or "").strip()

    # 1) Rules — first match wins; if multiple hit, pick the most restrictive tier
    hits: list[tuple[str, str, str]] = []
    for pattern, kind, tier, reason in RULE_SIGNALS:
        if pattern.search(text) or pattern.search(title):
            hits.append((kind, tier, reason))

    if hits:
        # Most restrictive = lowest tier rank
        kind, tier, reason = min(hits, key=lambda h: config.tier_rank(h[1]))
        return {
            "doc_kind": kind,
            "tier": tier,
            "reason": f"rule: {reason}",
            "confidence": 0.85,
            "source": "rules",
        }

    # 2) LLM fallback — with few-shot examples when KG available
    examples: list[dict[str, Any]] = []
    if kg is not None:
        try:
            from capabilities import tier_memory
            examples = tier_memory.nearest_corrections(
                kg=kg, title=title, text=text, k=tier_memory.TOPK_FEWSHOT,
            )
        except Exception as e:
            log.warning("fewshot_fetch_failed", extra={"error": str(e)})
    llm_result = _classify_llm(title=title, text=text, examples=examples)
    if llm_result:
        if examples:
            llm_result["source"] = "llm+fewshot"
            llm_result["fewshot_used"] = len(examples)
        return llm_result

    # 3) Conservative fallback
    return {
        "doc_kind": "general",
        "tier": config.DEFAULT_DOC_TIER,
        "reason": "no rule fired, LLM unavailable — default",
        "confidence": 0.2,
        "source": "fallback",
    }


# ---------------------------------------------------------------------------
def _classify_llm(
    *, title: str, text: str, examples: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    """Ask the LLM to classify. Returns None on failure."""
    prompt = _build_prompt(title=title, text=text, examples=examples or [])
    raw = llm.generate(
        model=config.MASTER_MODEL,
        prompt=prompt,
        json_mode=True,
        temperature=0.0,
        max_tokens=256,
    )
    parsed = llm.parse_json(raw) if raw else None
    if not parsed or not isinstance(parsed, dict):
        log.warning("sentinel_llm_parse_failed", extra={"raw_preview": (raw or "")[:120]})
        return None

    kind = parsed.get("doc_kind")
    tier = parsed.get("tier")
    reason = (parsed.get("reason") or "").strip()
    confidence = float(parsed.get("confidence") or 0.5)

    # Validate enums
    if kind not in KIND_DEFAULT_TIER:
        log.warning("sentinel_llm_bad_kind", extra={"got": kind})
        kind = "general"
    if tier not in config.TIERS:
        # Fall back to kind default
        tier = KIND_DEFAULT_TIER[kind]
        reason = (reason + " (tier coerced from kind default)").strip()
    if not reason:
        reason = f"LLM: {kind} → {tier}"
    return {
        "doc_kind": kind,
        "tier": tier,
        "reason": f"llm: {reason}",
        "confidence": max(0.0, min(1.0, confidence)),
        "source": "llm",
    }


def _build_prompt(
    *, title: str, text: str, examples: list[dict[str, Any]] | None = None,
) -> str:
    examples = examples or []
    fewshot_block = ""
    if examples:
        lines = ["", "Past CEO confirmations (most similar first — defer to these when in doubt):"]
        for ex in examples:
            lines.append(
                f"- title={ex.get('doc_title','')!r}  "
                f"final_tier={ex.get('ceo_tier','?')}  "
                f"kind={ex.get('ceo_kind') or ex.get('sentinel_kind') or '?'}"
            )
            if ex.get("ceo_reason"):
                lines.append(f"    ceo_reason: {ex['ceo_reason']}")
            elif ex.get("is_override"):
                lines.append(f"    (override of sentinel suggestion: {ex.get('sentinel_tier')})")
        fewshot_block = "\n".join(lines) + "\n"
    return f"""You are SENTINEL, a document tier classifier for a small company's internal copilot.

Classify the document into:
  - doc_kind: one of [contract, private, general, presentation, report, policy]
  - tier: one of [ceo, c_level, director, manager, everyone]
       ceo       = board, founder-only, equity, ultra-sensitive
       c_level   = exec staff, financials, HR private, comp, board decks
       director  = department heads — contracts, SOWs, dept ops, NDAs
       manager   = team-level docs, project ops
       everyone  = company-wide, handbook, all-hands, public policy

Rules:
  - Boring boilerplate → general / director.
  - Salary, performance review, HR file, board decks → c_level.
  - Equity / cap table / founder-only → ceo.
  - Handbook / code of conduct / all-hands → everyone / policy.
  - If unsure, default to director with low confidence.

Respond with a JSON object only:
{{"doc_kind": "...", "tier": "...", "reason": "<one short sentence>", "confidence": 0.0-1.0}}
{fewshot_block}
Document title: {title!r}

Document excerpt (first 8000 chars):
\"\"\"
{text}
\"\"\"
"""
