from __future__ import annotations

import unittest

from paper_data_agent import core
from paper_data_agent.agent_tools.paper_agent import PaperAgent, ToolRegistry
from paper_data_agent.retrieval.evaluation import evaluate_retrieval
from paper_data_agent.retrieval.index import PaperChunk, PaperIndex, SearchHit, tokenize


class CoreArchitectureTests(unittest.TestCase):
    def test_legacy_core_exports_focused_implementations(self) -> None:
        expected = {
            "PaperAgent": PaperAgent,
            "ToolRegistry": ToolRegistry,
            "PaperChunk": PaperChunk,
            "PaperIndex": PaperIndex,
            "SearchHit": SearchHit,
            "tokenize": tokenize,
            "evaluate_retrieval": evaluate_retrieval,
        }
        for name, implementation in expected.items():
            with self.subTest(name=name):
                self.assertIs(getattr(core, name), implementation)


if __name__ == "__main__":
    unittest.main()
