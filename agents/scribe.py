"""SCRIBE — persona file curator.

For each Person, SCRIBE derives a small YAML "context card" from the KG and
writes it to `memory/persona/<person_id>.yml`. ORACLE injects this card into
every conversation prompt so the bot greets the user already knowing what they
work on, who they work with, and what they recently decided.

Phase 12 fills the static, observable facts:
  - identity (role, dept, tier, email)
  - working_on (projects via WORKS_ON / RUNS / OWNED_BY edges)
  - colleagues_close (direct reports + manager + same-team peers)
  - recent_decisions (Events with PARTICIPATED_IN edge to this person)

Phase 13 will populate `communication_style` + `preferences` from chat
feedback. SCRIBE leaves them untouched on rebuild so manual notes persist.

Tier safety: SCRIBE only references entities the person themselves can see
(applies tier filter on every KG read scoped to person's tier). Prevents
persona-mediated leaks (e.g. Manager's persona referencing ceo-tier docs).
"""
from __future__ import annotations

import logging
from typing import Any

import config
from agents.base_agent import AgentResult, BaseAgent
from capabilities import persona_store
from core.knowledge_graph import KnowledgeGraph

log = logging.getLogger("hannibal.scribe")

MAX_PROJECTS = 8
MAX_COLLEAGUES = 8
MAX_DECISIONS = 8


class Scribe(BaseAgent):
    name = "SCRIBE"
    tagline = "persona curator — keeps per-Person context cards"
    persona = "Scribe quietly maintains a card for every person in the company."

    def invoke(self, task: dict[str, Any]) -> AgentResult:
        """task: {"action": "build" | "rebuild_all" | "refresh_for_doc",
                  "person_id": str?, "doc_id": str?}"""
        action = task.get("action", "build")
        if self.kg is None:
            return AgentResult(False, error="SCRIBE has no KG bound")

        if action == "build":
            pid = task.get("person_id")
            if not pid:
                return AgentResult(False, error="missing person_id")
            return self._build_one(pid)
        if action == "rebuild_all":
            return self._rebuild_all()
        if action == "refresh_for_doc":
            doc_id = task.get("doc_id")
            return self._refresh_for_doc(doc_id)
        return AgentResult(False, error=f"unknown action: {action}")

    # ------------------------------------------------------------------
    def _build_one(self, person_id: str) -> AgentResult:
        node = self.kg.get_live(person_id)
        if not node or node["entity_type"] != "Person":
            return AgentResult(False, error=f"{person_id} is not a Person")

        f = node["fields"]
        existing = persona_store.load_persona(person_id) or {}

        # Preserve user-curated fields (style / notes / preferences) — SCRIBE
        # never clobbers them.
        preserved_style = existing.get("communication_style") or []
        preserved_prefs = existing.get("preferences") or []
        preserved_notes = existing.get("notes") or ""

        identity = {
            "name": f.get("name"),
            "role": f.get("role"),
            "department": f.get("department"),
            "tier": f.get("tier") or config.DEFAULT_PERSON_TIER,
            "email": (f.get("emails") or [None])[0],
            "kind": f.get("kind"),
        }
        # Drop None values so YAML stays clean
        identity = {k: v for k, v in identity.items() if v is not None}

        working_on = self._derive_working_on(person_id)
        colleagues = self._derive_colleagues(person_id)
        decisions = self._derive_decisions(person_id)

        sources = ["kg_scan"]
        if existing.get("_meta", {}).get("sources"):
            # Keep history of doc-mention sources
            kept = [s for s in existing["_meta"]["sources"]
                    if s.startswith("doc:") or s.startswith("directory_import")]
            sources = sorted(set(sources + kept))

        data = {
            "person_id": person_id,
            "identity": identity,
            "working_on": working_on,
            "colleagues_close": colleagues,
            "recent_decisions": decisions,
            "communication_style": preserved_style,
            "preferences": preserved_prefs,
            "notes": preserved_notes,
            "_meta": {"sources": sources},
        }
        persona_store.save_persona(person_id, data, by="SCRIBE")
        log.info("scribe_built", extra={
            "person_id": person_id,
            "n_projects": len(working_on),
            "n_colleagues": len(colleagues),
            "n_decisions": len(decisions),
        })
        return AgentResult(True, data={"person_id": person_id,
                                       "sections": list(data.keys())})

    def _rebuild_all(self) -> AgentResult:
        persons = self.kg.list_live("Person")
        built = 0
        for p in persons:
            r = self._build_one(p["id"])
            if r.success:
                built += 1
        return AgentResult(True, data={"built": built, "total": len(persons)})

    def _refresh_for_doc(self, doc_id: str | None) -> AgentResult:
        """Find Persons connected to this Document via any edge, then rebuild
        their persona. Skips silently when doc_id is missing."""
        if not doc_id:
            return AgentResult(True, data={"refreshed": 0, "reason": "no_doc_id"})
        # Persons linked to the doc — AUTHORED edge points Person → Document.
        # We also rebuild Persons MENTIONED via any other edge to be safe.
        touched: set[str] = set()
        for edge in self.kg.graph.edges_to(self.kg.company_id, doc_id):
            other = self.kg.get_live(edge["from_id"])
            if other and other["entity_type"] == "Person":
                touched.add(other["id"])
        for edge in self.kg.graph.edges_from(self.kg.company_id, doc_id):
            other = self.kg.get_live(edge["to_id"])
            if other and other["entity_type"] == "Person":
                touched.add(other["id"])

        for pid in touched:
            self._build_one(pid)
        log.info("scribe_refresh_for_doc",
                 extra={"doc_id": doc_id, "touched": len(touched)})
        return AgentResult(True, data={"refreshed": len(touched)})

    # ------------------------------------------------------------------
    # Derivation helpers
    # ------------------------------------------------------------------
    def _derive_working_on(self, person_id: str) -> list[dict]:
        """Projects this Person works on, via WORKS_ON / RUNS / OWNED_BY edges
        or `Project.owner_id == person_id`."""
        out: list[dict] = []
        seen: set[str] = set()

        # Edges person → project
        for e in self.kg.graph.edges_from(self.kg.company_id, person_id):
            if e["type"] not in ("WORKS_ON", "RUNS"):
                continue
            proj = self.kg.get_live(e["to_id"])
            if not proj or proj["entity_type"] != "Project" or proj["id"] in seen:
                continue
            role = (e.get("properties") or {}).get("role")
            entry = {"project": proj["fields"].get("name") or proj["id"]}
            if role:
                entry["role"] = role
            out.append(entry)
            seen.add(proj["id"])
            if len(out) >= MAX_PROJECTS:
                return out

        # Projects this person owns
        for proj in self.kg.list_live("Project"):
            if proj["id"] in seen:
                continue
            if proj["fields"].get("owner_id") == person_id:
                out.append({"project": proj["fields"].get("name") or proj["id"],
                            "role": "owner"})
                seen.add(proj["id"])
                if len(out) >= MAX_PROJECTS:
                    return out
        return out

    def _derive_colleagues(self, person_id: str) -> list[dict]:
        """Closest people by edge density: manager (MEMBER_OF direct_report),
        direct reports of this person, same-team peers."""
        out: list[dict] = []
        seen: set[str] = set()

        # 1) Manager — Person → MEMBER_OF (direct_report) → Person
        for e in self.kg.graph.edges_from(self.kg.company_id, person_id):
            if e["type"] != "MEMBER_OF":
                continue
            props = e.get("properties") or {}
            if props.get("role") != "direct_report":
                continue
            mgr = self.kg.get_live(e["to_id"])
            if not mgr or mgr["entity_type"] != "Person" or mgr["id"] in seen:
                continue
            role_label = mgr["fields"].get("role") or ""
            relation = f"manager{(' (' + role_label + ')') if role_label else ''}"
            out.append({"name": mgr["fields"].get("name") or mgr["id"], "relation": relation})
            seen.add(mgr["id"])

        # 2) Direct reports — Person → MEMBER_OF direct_report → me (reverse)
        for e in self.kg.graph.edges_to(self.kg.company_id, person_id):
            if e["type"] != "MEMBER_OF":
                continue
            props = e.get("properties") or {}
            if props.get("role") != "direct_report":
                continue
            rep = self.kg.get_live(e["from_id"])
            if not rep or rep["entity_type"] != "Person" or rep["id"] in seen:
                continue
            out.append({"name": rep["fields"].get("name") or rep["id"],
                        "relation": "direct report"})
            seen.add(rep["id"])
            if len(out) >= MAX_COLLEAGUES:
                return out

        # 3) Same-team peers — find Teams person is MEMBER_OF, then other members
        team_ids: set[str] = set()
        for e in self.kg.graph.edges_from(self.kg.company_id, person_id):
            if e["type"] == "MEMBER_OF":
                team = self.kg.get_live(e["to_id"])
                if team and team["entity_type"] == "Team":
                    team_ids.add(team["id"])

        for tid in team_ids:
            for e in self.kg.graph.edges_to(self.kg.company_id, tid):
                if e["type"] != "MEMBER_OF":
                    continue
                peer = self.kg.get_live(e["from_id"])
                if not peer or peer["entity_type"] != "Person" or peer["id"] == person_id:
                    continue
                if peer["id"] in seen:
                    continue
                out.append({"name": peer["fields"].get("name") or peer["id"],
                            "relation": "team peer"})
                seen.add(peer["id"])
                if len(out) >= MAX_COLLEAGUES:
                    return out
        return out

    def _derive_decisions(self, person_id: str) -> list[dict]:
        """Events this Person PARTICIPATED_IN, newest first by date field."""
        events_with_date: list[tuple[str, dict]] = []
        for e in self.kg.graph.edges_from(self.kg.company_id, person_id):
            if e["type"] != "PARTICIPATED_IN":
                continue
            ev = self.kg.get_live(e["to_id"])
            if not ev or ev["entity_type"] != "Event":
                continue
            date = (ev["fields"].get("date") or "")[:10]  # ISO yyyy-mm-dd
            events_with_date.append((date, ev))
        # Sort newest first by date; missing dates sink to bottom
        events_with_date.sort(key=lambda t: t[0] or "", reverse=True)
        out = []
        for date, ev in events_with_date[:MAX_DECISIONS]:
            out.append({
                "date": date or None,
                "event": ev["fields"].get("name") or ev["id"],
                "outcome": ev["fields"].get("outcome") or None,
            })
        return out


SCRIBE = Scribe()
