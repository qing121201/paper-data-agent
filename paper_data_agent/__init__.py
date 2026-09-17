"""A small, reproducible data agent for academic PDF corpora."""

from .core import PaperAgent, PaperIndex
from .llm import LLMConfig, OpenAICompatibleClient
from .skills import SkillCatalog
from .workflow import ResearchWorkflowAgent

__all__ = [
    "LLMConfig",
    "OpenAICompatibleClient",
    "PaperAgent",
    "PaperIndex",
    "ResearchWorkflowAgent",
    "SkillCatalog",
]
