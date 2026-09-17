from copy import deepcopy
import unittest

from paper_data_agent.presentation_workspace import replace_slide


class SlideRevisionTests(unittest.TestCase):
    def setUp(self):
        self.spec = {"title": "文稿", "subtitle": "课题", "slides": [
            {"title": "背景", "bullets": ["原文观点"], "source": "Paper A p1"},
            {"title": "实验", "bullets": ["原文数据"], "source": "Paper A p3"},
        ]}

    def test_revision_only_changes_selected_page_and_keeps_source(self):
        before = deepcopy(self.spec)
        updated = replace_slide(self.spec, 2, {"title": "实验比较", "bullets": ["简短解释"]})
        self.assertEqual(self.spec, before)
        self.assertEqual(updated["slides"][0], before["slides"][0])
        self.assertEqual(updated["slides"][1]["source"], "Paper A p3")
        self.assertEqual(updated["slides"][1]["title"], "实验比较")

    def test_cover_edit_leaves_all_content_pages_intact(self):
        updated = replace_slide(self.spec, 0, {"title": "新标题"})
        self.assertEqual(updated["slides"], self.spec["slides"])
        self.assertEqual(updated["subtitle"], "课题")

    def test_rejects_invalid_page_or_overlong_text_instead_of_truncating(self):
        with self.assertRaises(ValueError):
            replace_slide(self.spec, 99, {})
        with self.assertRaises(ValueError):
            replace_slide(self.spec, 1, {"bullets": ["text"] * 8})
        with self.assertRaises(ValueError):
            replace_slide(self.spec, 1, {"bullets": "not a list"})
