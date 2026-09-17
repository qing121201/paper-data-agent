import unittest

from paper_data_agent.markdown_render import clean_markdown_markers, inline_segments, parse_markdown_blocks


class MarkdownRenderTests(unittest.TestCase):
    def test_table_separator_becomes_real_table_block(self) -> None:
        blocks = parse_markdown_blocks(
            "| 目标 | 查询词 | 来源 |\n|---|---|---|\n| SWE-bench | `SWE-agent` | **arXiv** |"
        )
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0].kind, "table")
        self.assertEqual(blocks[0].rows[0], ("目标", "查询词", "来源"))
        self.assertEqual(blocks[0].rows[1], ("SWE-bench", "SWE-agent", "arXiv"))

    def test_inline_markers_are_not_shown(self) -> None:
        segments = inline_segments("结论 **重要**，模型为 `deepseek-flash`。")
        self.assertIn(("重要", "bold"), segments)
        self.assertIn(("deepseek-flash", "code"), segments)
        self.assertNotIn("**", "".join(text for text, _style in segments))

    def test_headings_bullets_and_quotes_are_classified(self) -> None:
        blocks = parse_markdown_blocks("## 结果\n---\n- 第一项\n> 注意事项")
        self.assertEqual([block.kind for block in blocks], ["heading", "horizontal_rule", "bullet", "quote"])
        self.assertEqual(clean_markdown_markers("**作者与出处存疑**"), "作者与出处存疑")

    def test_inline_spacing_is_preserved(self) -> None:
        rendered = "".join(text for text, _style in inline_segments("(2025). *Paper title*. DOI"))
        self.assertEqual(rendered, "(2025). Paper title. DOI")

    def test_markdown_fence_is_rendered_instead_of_shown_as_code(self) -> None:
        blocks = parse_markdown_blocks("```markdown\n## 结果\n- 第一项\n```")
        self.assertEqual([block.kind for block in blocks], ["heading", "bullet"])


if __name__ == "__main__":
    unittest.main()
