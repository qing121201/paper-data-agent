from __future__ import annotations

import unittest

from paper_data_agent import workflow
from paper_data_agent.research_workflow.agent import ResearchWorkflowAgent
from paper_data_agent.research_workflow.execution import ExecutionMixin
from paper_data_agent.research_workflow.models import AgentPlan, WorkflowResult
from paper_data_agent.research_workflow.planning import PlanningMixin
from paper_data_agent.research_workflow.text import route_skill


class WorkflowArchitectureTests(unittest.TestCase):
    def test_legacy_workflow_exports_focused_implementations(self) -> None:
        self.assertIs(workflow.ResearchWorkflowAgent, ResearchWorkflowAgent)
        self.assertIs(workflow.AgentPlan, AgentPlan)
        self.assertIs(workflow.WorkflowResult, WorkflowResult)
        self.assertIs(workflow.route_skill, route_skill)

    def test_workflow_composes_separate_planning_and_execution(self) -> None:
        self.assertTrue(issubclass(ResearchWorkflowAgent, PlanningMixin))
        self.assertTrue(issubclass(ResearchWorkflowAgent, ExecutionMixin))
        self.assertNotIn("plan", ResearchWorkflowAgent.__dict__)
        self.assertNotIn("_collect_steps", ResearchWorkflowAgent.__dict__)
        self.assertIn("plan", PlanningMixin.__dict__)
        self.assertIn("_collect_steps", ExecutionMixin.__dict__)


if __name__ == "__main__":
    unittest.main()
