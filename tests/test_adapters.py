import unittest

from paper_data_agent.adapters import normalize_mindmap_theme


class AdapterTests(unittest.TestCase):
    def test_default_mindmap_theme_maps_to_air(self) -> None:
        self.assertEqual(normalize_mindmap_theme("default"), ("air", True))

    def test_unknown_mindmap_theme_falls_back_to_air(self) -> None:
        self.assertEqual(normalize_mindmap_theme("paper-white"), ("air", True))

    def test_supported_mindmap_theme_is_preserved(self) -> None:
        self.assertEqual(normalize_mindmap_theme("zen"), ("zen", False))


if __name__ == "__main__":
    unittest.main()
