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


# ---------------------------------------------------------------------------
# Entities
# ---------------------------------------------------------------------------
class Person(MemoryFields):
    id: str
    company_id: str
    name: str
    email: str | None = None
    contact: str | None = None
    tenure_since: str | None = None  # ISO date
    expertise: list[str] = Field(default_factory=list)


class Team(MemoryFields):
    id: str
    company_id: str
    name: str
    mission: str | None = None
    lead_id: str | None = None
    domain: str | None = None
    parent_team_id: str | None = None


class Project(MemoryFields):
    id: str
    company_id: str
    name: str
    status: str | None = None  # "In Progress" | "On Hold" | "Done" | "Cancelled"
    team_id: str | None = None
    started: str | None = None
    target: str | None = None
    description: str | None = None


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
