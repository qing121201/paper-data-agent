"""Desktop UI components for Paper Data Agent."""

from .chat_page import ChatPageMixin
from .home_page import HomePageMixin
from .library_page import LibraryPageMixin
from .model_settings import ModelSettingsMixin
from .presentation_page import PresentationPanel
from .theme import THEMES, ThemeMixin

__all__ = [
    "ChatPageMixin", "HomePageMixin", "LibraryPageMixin", "ModelSettingsMixin", "PresentationPanel",
    "THEMES", "ThemeMixin",
]
