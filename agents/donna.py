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

    Per-entity rules from the plan:
      Person : same name+email match → any other field differs → conflict
      Rule   : same title match → content cosine < 0.85 → conflict
      Project: same name → status changed → NOT conflict, just update
      Team   : same name → lead_id or parent_team_id differs → conflict
    """
    cand_f = candidate
    live_f = live["fields"]

    if entity_type == "Person":
        diffs = {}
        for key in ("role", "email"):
            cv = (cand_f.get(key) or "").strip().lower()
            lv = (live_f.get(key) or "").strip().lower()
            if cv and lv and cv != lv:
                diffs[key] = {"live": lv, "candidate": cv}
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
        # Status change = update, not conflict
        return None

    if entity_type == "Team":
        diffs = {}
        for key in ("lead_id", "parent_team_id"):
            cv = (cand_f.get(key) or "").strip()
            lv = (live_f.get(key) or "").strip()
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
        """
        if self.kg is None:
            return AgentResult(False, error="DONNA has no KG bound")

        action = task.get("action", "scan_count")

        if action == "scan_staleness":
            return self._scan_staleness()
        if action == "scan_count":
            return self._scan_count()
        return AgentResult(False, error=f"unknown action: {action}")

    def _scan_count(self) -> AgentResult:
        counts = {"stale_rules": 0, "stale_persons": 0, "stale_teams": 0, "stale_projects": 0}
        for et in ("Rule", "Person", "Team", "Project"):
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

        for et in ("Rule", "Person", "Team", "Project"):
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


DONNA = Donna()
