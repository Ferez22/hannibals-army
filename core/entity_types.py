"""Knowledge graph entity types. Pure data shapes — no logic."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Memory fields — present on every live node
# ---------------------------------------------------------------------------
class MemoryFields(BaseModel):
    created_at: datetime
    last_verified_at: datetime
    source_count: int = 0
    confidence: float = 0.0  # min(1, source_count/3) - 0.3*contradictions, clamped [0,1]
    confirmed: bool = False  # admin reviewed + accepted (Phase 10D)
    confirmed_by: str | None = None
    confirmed_at: datetime | None = None


# ---------------------------------------------------------------------------
# Entities
# ---------------------------------------------------------------------------
TierLabel = Literal["ceo", "c_level", "director", "manager", "everyone"]
DocKind = Literal["contract", "private", "general", "presentation", "report", "policy"]


class Person(MemoryFields):
    id: str
    company_id: str
    name: str
    kind: Literal["employee", "external", "unknown"] = "unknown"
    emails: list[str] = Field(default_factory=list)
    contact: str | None = None
    role: str | None = None
    sub_roles: list[str] = Field(default_factory=list)
    tenure_since: str | None = None  # ISO date
    expertise: list[str] = Field(default_factory=list)
    photo_path: str | None = None  # relative to REPO_ROOT
    external_company: str | None = None  # only set when kind == "external"
    telegram_chat_id: str | None = None  # for Telegram bot auth (CEO edits, identified Q&A)
    tier: TierLabel = "everyone"
    tier_confirmed: bool = False  # CEO must confirm in Pending before sender_tier elevates


class Team(MemoryFields):
    id: str
    company_id: str
    name: str
    kind: Literal["internal", "external"] = "internal"
    external_org: str | None = None  # required when kind == "external"
    mission: str | None = None
    lead_id: str | None = None
    domain: str | None = None
    parent_team_id: str | None = None


class Project(MemoryFields):
    id: str
    company_id: str
    name: str
    kind: Literal["internal", "external"] = "internal"
    status: str | None = None  # "In Progress" | "On Hold" | "Done" | "Cancelled"
    client_id: str | None = None  # required when kind == "external"
    team_id: str | None = None
    owner_id: str | None = None  # Person responsible — ownership beats tier (Phase 10C)
    started: str | None = None
    target: str | None = None
    description: str | None = None


class Client(MemoryFields):
    id: str
    company_id: str
    name: str
    industry: str | None = None
    contact_person_id: str | None = None  # FK to a Person (likely external)
    contact_email: str | None = None
    domicile: str | None = None
    status: Literal["active", "paused", "closed"] = "active"
    notes: str | None = None


class Rule(MemoryFields):
    id: str
    company_id: str
    category: Literal["policy", "process", "value"]
    title: str
    content: str
    owner_id: str | None = None
    notify_person_id: str | None = None
    valid_until: str | None = None


class Event(MemoryFields):
    id: str
    company_id: str
    name: str
    date: str | None = None  # ISO date
    type: str | None = None
    outcome: str | None = None


class Document(MemoryFields):
    id: str
    company_id: str
    title: str
    type: str  # pdf | docx | pptx | xlsx | image | url
    date: str | None = None
    raw_path: str | None = None
    ingested_at: datetime | None = None
    # Tier / classification (Phase 10A)
    tier: TierLabel = "director"
    doc_kind: DocKind | None = None
    tier_reason: str | None = None
    tier_confirmed_by: str | None = None
    tier_confirmed_at: datetime | None = None
    owner_id: str | None = None  # Person who owns this doc — ownership beats tier


# ---------------------------------------------------------------------------
# Edges — relationships between nodes. Properties carried on edge row.
# ---------------------------------------------------------------------------
EdgeType = Literal[
    "MEMBER_OF",
    "PARTICIPATED_IN",
    "AUTHORED",
    "CHILD_OF",
    "RUNS",
    "REFERENCES",
    "EXTRACTED_FROM",
    "OWNED_BY",
    "NOTIFY",
    "WORKS_ON",            # Team or Person → Project
    "BELONGS_TO_CLIENT",   # Person → Client (external person tied to a client)
]


class Edge(BaseModel):
    company_id: str
    from_id: str
    type: EdgeType
    to_id: str
    # MEMBER_OF carries role + tasks + since + active
    role: str | None = None
    tasks: list[str] = Field(default_factory=list)
    since: str | None = None
    active: bool = True


# ---------------------------------------------------------------------------
# Raw input — produced by RAGNAR, consumed by CARTOGRAPHER
# ---------------------------------------------------------------------------
class RawDocument(BaseModel):
    source: str  # file path or URL
    format: str  # pdf | docx | pptx | xlsx | image | url
    raw_text: str
    metadata: dict = Field(default_factory=dict)
    extracted_at: datetime
