"""Compatibility facade for paper retrieval and evidence tools.

Focused implementations live in :mod:`paper_data_agent.retrieval` and
:mod:`paper_data_agent.agent_tools`. Existing imports remain supported.
"""

from .agent_tools.paper_agent import PaperAgent, ToolRegistry
from .retrieval.evaluation import evaluate_retrieval
from .retrieval.index import (
    TOKEN_PATTERN,
    PaperChunk,
    PaperIndex,
    SearchHit,
    _extract_pdf_pages,
    tokenize,
)

__all__ = [
    "TOKEN_PATTERN", "PaperAgent", "PaperChunk", "PaperIndex", "SearchHit",
    "ToolRegistry", "_extract_pdf_pages", "evaluate_retrieval", "tokenize",
]
