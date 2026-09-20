"""Data contracts for research workflow planning and results."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


ProgressCallback = Callable[[int, str], None]


@dataclass(slots=True)
class WorkflowResult:
    skill: str
    answer: str
    evidence_brief: str
    loaded_files: list[str]
    omitted_files: list[str]
    dry_run: bool
    steps: list[dict[str, Any]] = field(default_factory=list)


@dataclass(slots=True)
class AgentPlan:
    tool: str
    skill: str
    search_query: str
    reason: str
    arguments: dict[str, Any]
