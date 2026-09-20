"""Compatibility facade for the paper library domain.

New code should import focused implementations from ``library_domain``. This
module keeps the original public API stable for the GUI, scripts, and users.
"""

from .library_domain import (
    ImportResult,
    LibraryInfo,
    LibraryManager,
    PaperLibrary,
    PaperRecord,
    SearchImportResult,
)

__all__ = [
    "ImportResult",
    "LibraryInfo",
    "LibraryManager",
    "PaperLibrary",
    "PaperRecord",
    "SearchImportResult",
]
