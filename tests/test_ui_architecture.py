from __future__ import annotations

import unittest

from paper_data_agent.gui import PaperAgentGUI
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


if __name__ == "__main__":
    unittest.main()
