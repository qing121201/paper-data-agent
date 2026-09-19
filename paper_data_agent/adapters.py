"""Compatibility facade for controlled research-tool adapters.

New code should import focused components from :mod:`paper_data_agent.tool_adapters`.
The legacy exports remain stable for existing callers and tests.
"""

from __future__ import annotations

from pathlib import Path

from .tool_adapters import (
    AcademicSearchMixin,
    AdapterResult,
    MindmapAdapterMixin,
    PresentationAdapterMixin,
    PROJECT_ROOT,
    ScientificFigureAdapterMixin,
    WINDOWS_NO_WINDOW,
    normalize_mindmap_theme,
)


class ResearchToolAdapters(
    AcademicSearchMixin,
    MindmapAdapterMixin,
    ScientificFigureAdapterMixin,
    PresentationAdapterMixin,
):
    """Compatibility facade that composes focused, controlled adapters."""

    def __init__(self, output_dir: Path):
        self.output_dir = output_dir.resolve()
        self.output_dir.mkdir(parents=True, exist_ok=True)
