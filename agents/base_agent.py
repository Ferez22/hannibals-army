"""Base agent — shared interface for all army members."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from core.knowledge_graph import KnowledgeGraph


@dataclass
class AgentResult:
    success: bool
    data: Any = None
    cited_nodes: list[str] = field(default_factory=list)
    error: str | None = None


class BaseAgent:
    """All agents share this contract.

    Concrete agents override invoke().
    """

    name: str = "base"
    tagline: str = ""
    persona: str = ""

    def __init__(self, kg: "KnowledgeGraph | None" = None) -> None:
        self.kg = kg

    def invoke(self, task: dict[str, Any]) -> AgentResult:
        raise NotImplementedError(f"{self.name} has no invoke() implementation yet")

    def __repr__(self) -> str:
        return f"<Agent {self.name}>"
