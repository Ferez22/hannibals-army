"""DONNA — auditor.

Responsibilities:
  - Detect conflicts when CARTOGRAPHER tries to promote against existing live nodes
  - Scan all live nodes for staleness, route signals
  - Dispatch rule notifications when rule entity goes stale
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from rapidfuzz import fuzz

import config
from agents.base_agent import AgentResult, BaseAgent
from capabilities import notifier
from core.knowledge_graph import KnowledgeGraph

log = logging.getLogger("hannibal.donna")


# Map entity type → staleness threshold key in config.STALENESS_THRESHOLDS
_TYPE_TO_THRESHOLD = {
    "Person":  "person_role",
    "Team":    "team_structure",
    "Project": "project_status",
    "Client":  "client_relationship",
    "Rule":    "rule_policy",
    "Event":   "event",
}


def is_stale(node: dict) -> bool:
    """Compute on read: now - last_verified_at > threshold_for(type)."""
    threshold_days = config.STALENESS_THRESHOLDS.get(
        _TYPE_TO_THRESHOLD.get(node["entity_type"], "")
    )
    if threshold_days is None:
        return False
    try:
        last = datetime.fromisoformat(node["last_verified_at"])
    except (ValueError, TypeError):
        return False
    age_days = (datetime.now() - last).days
    return age_days > threshold_days


def detect_conflict(entity_type: str, candidate: dict, live: dict) -> dict | None:
    """Return a conflict description if candidate disagrees with existing live, else None.

    Per-entity rules:
      Person  : role differs → role_conflict (user picks: sub-role / replace / dismiss)
                kind differs → kind_conflict
                external_company differs → conflict
                new emails → auto-merge, NO conflict (Cartographer handles)
                Other fields differ → standard conflict
      Rule    : same title → content sim < 0.85 → conflict
      Project : status change is OK, not conflict
      Team    : same name → lead_id or parent differs → conflict
    """
    cand_f = candidate
    live_f = live["fields"]

    if entity_type == "Person":
        diffs: dict = {}
        # role: special — flagged as role_conflict for action-picker
        cv_role = (cand_f.get("role") or "").strip()
        lv_role = (live_f.get("role") or "").strip()
        if cv_role and lv_role and cv_role.lower() != lv_role.lower():
            # Only flag if candidate isn't already in live sub_roles
            existing_sub = {s.lower() for s in (live_f.get("sub_roles") or [])}
            if cv_role.lower() not in existing_sub:
                diffs["role"] = {"live": lv_role, "candidate": cv_role}

        # kind: identity-level conflict
        cv_kind = cand_f.get("kind")
        lv_kind = live_f.get("kind")
        if cv_kind and lv_kind and cv_kind != "unknown" and cv_kind != lv_kind:
            diffs["kind"] = {"live": lv_kind, "candidate": cv_kind}

        # external_company
        cv_company = (cand_f.get("external_company") or "").strip()
        lv_company = (live_f.get("external_company") or "").strip()
        if cv_company and lv_company and cv_company.lower() != lv_company.lower():
            diffs["external_company"] = {"live": lv_company, "candidate": cv_company}

        if diffs:
            return {"diffs": diffs}
        return None

    if entity_type == "Rule":
        cand_content = (cand_f.get("content") or cand_f.get("title") or "").strip()
        live_content = (live_f.get("content") or live_f.get("title") or "").strip()
        if cand_content and live_content:
            sim = fuzz.token_set_ratio(cand_content, live_content) / 100.0
            if sim < 0.85:
                return {"diffs": {"content": {"live": live_content, "candidate": cand_content, "similarity": sim}}}
        return None

    if entity_type == "Project":
        diffs: dict = {}
        # Status change = update, not conflict (preserved behaviour)
        # kind change IS a conflict (internal → external is identity-level)
        cv_kind = (cand_f.get("kind") or "").strip().lower()
        lv_kind = (live_f.get("kind") or "").strip().lower()
        if cv_kind and lv_kind and cv_kind != lv_kind:
            diffs["kind"] = {"live": lv_kind, "candidate": cv_kind}
        # client_id mismatch = conflict (one project shouldn't switch clients silently)
        cv_client = (cand_f.get("client_id") or "").strip()
        lv_client = (live_f.get("client_id") or "").strip()
        if cv_client and lv_client and cv_client != lv_client:
            diffs["client_id"] = {"live": lv_client, "candidate": cv_client}
        if diffs:
            return {"diffs": diffs}
        return None

    if entity_type == "Team":
        diffs = {}
        for key in ("lead_id", "parent_team_id"):
            cv = (cand_f.get(key) or "").strip()
            lv = (live_f.get(key) or "").strip()
            if cv and lv and cv != lv:
                diffs[key] = {"live": lv, "candidate": cv}
        cv_kind = (cand_f.get("kind") or "").strip().lower()
        lv_kind = (live_f.get("kind") or "").strip().lower()
        if cv_kind and lv_kind and cv_kind != lv_kind:
            diffs["kind"] = {"live": lv_kind, "candidate": cv_kind}
        cv_org = (cand_f.get("external_org") or "").strip().lower()
        lv_org = (live_f.get("external_org") or "").strip().lower()
        if cv_org and lv_org and cv_org != lv_org:
            diffs["external_org"] = {"live": lv_org, "candidate": cv_org}
        if diffs:
            return {"diffs": diffs}
        return None

    if entity_type == "Client":
        diffs = {}
        for key in ("domicile", "industry"):
            cv = (cand_f.get(key) or "").strip().lower()
            lv = (live_f.get(key) or "").strip().lower()
            if cv and lv and cv != lv:
                diffs[key] = {"live": lv, "candidate": cv}
        if diffs:
            return {"diffs": diffs}
        return None

    return None


class Donna(BaseAgent):
    name = "DONNA"
    tagline = "auditor — staleness, conflicts, rule notifications"
    persona = "Donna audits the graph."

    def __init__(self, kg: KnowledgeGraph | None = None) -> None:
        super().__init__(kg=kg)

    def invoke(self, task: dict[str, Any]) -> AgentResult:
        """Action dispatch.

        task: {"action": "scan_staleness"}   → scan all live, queue stale ones
              {"action": "scan_count"}       → return counts (cheap)
              {"action": "scan_all"}         → staleness scan + conflict summary + Telegram digest + log
        """
        if self.kg is None:
            return AgentResult(False, error="DONNA has no KG bound")

        action = task.get("action", "scan_count")

        if action == "scan_staleness":
            return self._scan_staleness()
        if action == "scan_count":
            return self._scan_count()
        if action == "scan_all":
            return self._scan_all()
        return AgentResult(False, error=f"unknown action: {action}")

    def _scan_count(self) -> AgentResult:
        counts = {
            "stale_rules": 0, "stale_persons": 0,
            "stale_teams": 0, "stale_projects": 0, "stale_clients": 0,
        }
        for et in ("Rule", "Person", "Team", "Project", "Client"):
            for node in self.kg.list_live(et):
                if is_stale(node):
                    counts[f"stale_{et.lower()}s" if et != "Person" else "stale_persons"] += 1
        return AgentResult(True, data=counts)

    def _scan_staleness(self) -> AgentResult:
        """For each stale node: queue Review (or notify Rule owner)."""
        queued_review = 0
        queued_notifications = 0

        existing_review = self.kg.graph.list_review_queue(self.kg.company_id)
        # Build set of (kind, live_node_id) already queued (unresolved)
        already_queued = {(r["kind"], r["live_node_id"]) for r in existing_review}

        for et in ("Rule", "Person", "Team", "Project", "Client"):
            for node in self.kg.list_live(et):
                if not is_stale(node):
                    continue

                if et == "Rule":
                    if ("rule_notification", node["id"]) in already_queued:
                        continue
                    notifier.notify_rule_owner(
                        self.kg.graph,
                        company_id=self.kg.company_id,
                        rule_id=node["id"],
                        rule_title=node["fields"].get("title", ""),
                        notify_person_id=node["fields"].get("notify_person_id"),
                        reason="stale_threshold_exceeded",
                    )
                    queued_notifications += 1
                else:
                    if ("staleness", node["id"]) in already_queued:
                        continue
                    self.kg.graph.queue_for_review(
                        company_id=self.kg.company_id,
                        kind="staleness",
                        entity_type=et,
                        live_node_id=node["id"],
                        candidate_node_id=None,
                        details={
                            "name": node["fields"].get("name") or node["fields"].get("title", ""),
                            "last_verified_at": node["last_verified_at"],
                            "reason": "stale_threshold_exceeded",
                        },
                    )
                    queued_review += 1

        return AgentResult(
            True,
            data={
                "queued_review": queued_review,
                "queued_notifications": queued_notifications,
            },
        )


    def _scan_all(self) -> AgentResult:
        """Full scan: staleness + open conflicts + Telegram digest + record in scan_log.

        Composes _scan_staleness() then summarises stale + unresolved conflicts
        from the review_queue. Returns a dict with everything that was queued.
        """
        if self.kg is None:
            return AgentResult(False, error="DONNA has no KG bound")

        stale_res = self._scan_staleness()
        if not stale_res.success:
            return stale_res
        stale_data = stale_res.data or {}

        # Collect concrete items from review_queue for digest
        review_items = self.kg.graph.list_review_queue(self.kg.company_id, resolved=False)
        stale_rules: list[dict] = []
        stale_other: list[dict] = []
        new_conflicts: list[dict] = []
        for r in review_items:
            d = r.get("details") or {}
            if r["kind"] == "rule_notification":
                stale_rules.append({
                    "title": d.get("rule_title") or r.get("live_node_id"),
                    "reason": d.get("reason"),
                })
            elif r["kind"] == "staleness":
                stale_other.append({
                    "entity_type": r.get("entity_type"),
                    "name": d.get("name") or r.get("live_node_id"),
                })
            elif r["kind"] in ("conflict", "role_conflict"):
                new_conflicts.append({
                    "entity_type": r.get("entity_type"),
                    "name": (d.get("live_fields") or {}).get("name") or r.get("live_node_id"),
                })

        # Fire Telegram digest (best-effort, never blocks scan result)
        try:
            from capabilities import notifier
            notifier.send_scan_digest(
                stale_rules=stale_rules,
                stale_other=stale_other,
                new_conflicts=new_conflicts,
            )
        except Exception as e:
            log.warning("digest_send_failed", extra={"error": str(e)})

        # Record scan
        self.kg.graph.record_scan(
            company_id=self.kg.company_id,
            kind="auto",
            queued_review=stale_data.get("queued_review", 0),
            queued_notifications=stale_data.get("queued_notifications", 0),
        )

        return AgentResult(
            True,
            data={
                "queued_review": stale_data.get("queued_review", 0),
                "queued_notifications": stale_data.get("queued_notifications", 0),
                "stale_rules": stale_rules,
                "stale_other": stale_other,
                "open_conflicts": new_conflicts,
            },
        )


DONNA = Donna()
