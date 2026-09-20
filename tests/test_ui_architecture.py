from __future__ import annotations

import unittest

from paper_data_agent.gui import PaperAgentGUI
from paper_data_agent.ui.chat_page import ChatPageMixin
from paper_data_agent.ui.home_page import HomePageMixin
from paper_data_agent.ui.library_page import LibraryPageMixin
from paper_data_agent.ui.theme import THEMES, ThemeMixin


class UIArchitectureTests(unittest.TestCase):
    def test_main_window_uses_separate_theme_component(self) -> None:
        self.assertTrue(issubclass(PaperAgentGUI, ThemeMixin))
        self.assertNotIn("_apply_theme", PaperAgentGUI.__dict__)
        self.assertIn("纸张暖色", THEMES)

    def test_all_themes_expose_required_palette_tokens(self) -> None:
        required = {
            "bg", "surface", "field", "text", "muted", "border",
            "accent", "accent_hover", "success", "warning",
        }
        for name, palette in THEMES.items():
            with self.subTest(theme=name):
                self.assertTrue(required.issubset(palette))

    def test_main_window_uses_separate_home_page_component(self) -> None:
        self.assertTrue(issubclass(PaperAgentGUI, HomePageMixin))
        self.assertNotIn("_build_home_tab", PaperAgentGUI.__dict__)
        self.assertNotIn("_refresh_discovery", PaperAgentGUI.__dict__)
        self.assertIn("_build_home_tab", HomePageMixin.__dict__)
        self.assertIn("_refresh_discovery", HomePageMixin.__dict__)

    def test_main_window_uses_separate_library_page_component(self) -> None:
        self.assertTrue(issubclass(PaperAgentGUI, LibraryPageMixin))
        for method in ("_build_import_tab", "_import_folder", "_remove_selected_paper"):
            with self.subTest(method=method):
                self.assertNotIn(method, PaperAgentGUI.__dict__)
                self.assertIn(method, LibraryPageMixin.__dict__)

    def test_main_window_uses_separate_chat_page_component(self) -> None:
        self.assertTrue(issubclass(PaperAgentGUI, ChatPageMixin))
        for method in ("_build_chat_tab", "_insert_markdown", "_send_chat"):
            with self.subTest(method=method):
                self.assertNotIn(method, PaperAgentGUI.__dict__)
                self.assertIn(method, ChatPageMixin.__dict__)


if __name__ == "__main__":
    unittest.main()
