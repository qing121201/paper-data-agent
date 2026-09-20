"""Desktop UI components for Paper Data Agent."""

from .chat_page import ChatPageMixin
from .home_page import HomePageMixin
from .library_page import LibraryPageMixin
from .theme import THEMES, ThemeMixin

__all__ = ["ChatPageMixin", "HomePageMixin", "LibraryPageMixin", "THEMES", "ThemeMixin"]
