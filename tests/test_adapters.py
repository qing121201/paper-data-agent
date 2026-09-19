import unittest

from paper_data_agent.adapters import AdapterResult, ResearchToolAdapters, normalize_mindmap_theme
from paper_data_agent.tool_adapters.academic_search import AcademicSearchMixin
from paper_data_agent.tool_adapters.mindmap import MindmapAdapterMixin
from paper_data_agent.tool_adapters.presentation import PresentationAdapterMixin
from paper_data_agent.tool_adapters.scientific_figure import ScientificFigureAdapterMixin


class AdapterTests(unittest.TestCase):
    def test_default_mindmap_theme_maps_to_air(self) -> None:
        self.assertEqual(normalize_mindmap_theme("default"), ("air", True))

    def test_unknown_mindmap_theme_falls_back_to_air(self) -> None:
        self.assertEqual(normalize_mindmap_theme("paper-white"), ("air", True))

    def test_supported_mindmap_theme_is_preserved(self) -> None:
        self.assertEqual(normalize_mindmap_theme("zen"), ("zen", False))

    def test_online_search_is_supplied_by_separate_adapter_module(self) -> None:
        self.assertTrue(issubclass(ResearchToolAdapters, AcademicSearchMixin))
        self.assertNotIn("online_search", ResearchToolAdapters.__dict__)
        self.assertIn("online_search", AcademicSearchMixin.__dict__)

    def test_adapter_result_markdown_contract_is_unchanged(self) -> None:
        result = AdapterResult("demo", "完成", ["result.md"], {"count": 1})
        rendered = result.as_markdown()
        self.assertIn("- `result.md`", rendered)
        self.assertIn("```json", rendered)
        self.assertIn('\"count\": 1', rendered)

    def test_facade_composes_all_focused_adapters(self) -> None:
        for component, method in (
            (MindmapAdapterMixin, "create_mindmap"),
            (ScientificFigureAdapterMixin, "create_scientific_figure"),
            (PresentationAdapterMixin, "create_presentation"),
        ):
            with self.subTest(component=component.__name__):
                self.assertTrue(issubclass(ResearchToolAdapters, component))
                self.assertNotIn(method, ResearchToolAdapters.__dict__)
                self.assertIn(method, component.__dict__)


if __name__ == "__main__":
    unittest.main()
