"""Compatibility facade for the evidence-grounded research workflow."""

from .research_workflow.agent import ResearchWorkflowAgent
from .research_workflow.models import AgentPlan, ProgressCallback, WorkflowResult
from .research_workflow.text import (
    ROUTES,
    coverage_note,
    prettify_paper_references,
    remove_reading_process_branches,
    route_skill,
)

__all__ = [
    "ROUTES", "AgentPlan", "ProgressCallback", "ResearchWorkflowAgent", "WorkflowResult",
    "coverage_note", "prettify_paper_references", "remove_reading_process_branches", "route_skill",
]
