"""Controlled external tool adapters."""

from .academic_search import AcademicSearchMixin
from .common import AdapterResult, PROJECT_ROOT, WINDOWS_NO_WINDOW, normalize_mindmap_theme, slug
from .mindmap import MindmapAdapterMixin
from .presentation import PresentationAdapterMixin
from .scientific_figure import ScientificFigureAdapterMixin

__all__ = [
    "AcademicSearchMixin", "AdapterResult", "MindmapAdapterMixin", "PresentationAdapterMixin",
    "PROJECT_ROOT", "ScientificFigureAdapterMixin", "WINDOWS_NO_WINDOW",
    "normalize_mindmap_theme", "slug",
]
