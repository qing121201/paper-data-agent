from pathlib import Path
import tempfile
import unittest

from paper_data_agent.core import PaperAgent, PaperChunk, PaperIndex, ToolRegistry, tokenize


def sample_index() -> PaperIndex:
    return PaperIndex(
        [
            PaperChunk("a", "Code Review", "a.pdf", 2, 0, "automatic code review with repository context"),
            PaperChunk("b", "Software Evolution", "b.pdf", 4, 0, "long horizon continuous software evolution"),
        ]
    )


class PaperAgentTests(unittest.TestCase):
    def test_tokenize_mixed_language(self) -> None:
        self.assertEqual(tokenize("Agent处理PDF"), ["agent", "处", "理", "pdf"])

    def test_bm25_returns_relevant_source(self) -> None:
        hits = sample_index().search("repository code review", top_k=1)
        self.assertEqual(hits[0].title, "Code Review")
        self.assertEqual(hits[0].page, 2)

    def test_brief_contains_provenance(self) -> None:
        brief = PaperAgent(sample_index()).run("build_brief", query="software evolution", top_k=1)
        self.assertIn("Software Evolution", brief)
        self.assertIn("Page: 4", brief)
        self.assertIn("b.pdf", brief)

    def test_survey_corpus_includes_each_paper(self) -> None:
        index = PaperIndex(
            [
                PaperChunk("a", "Paper A", "a.pdf", 1, 0, "first abstract about agents"),
                PaperChunk("a", "Paper A", "a.pdf", 2, 1, "later page"),
                PaperChunk("b", "Paper B", "b.pdf", 1, 0, "second abstract about tools"),
            ]
        )
        survey = PaperAgent(index).run("survey_corpus")
        self.assertIn("Included papers: 2 of 2", survey)
        self.assertIn("Paper A", survey)
        self.assertIn("Paper B", survey)

    def test_full_paper_reading_is_all_or_nothing(self) -> None:
        index = PaperIndex(
            [
                PaperChunk("a", "Paper A", "a.pdf", 1, 0, "A_PAGE_ONE"),
                PaperChunk("a", "Paper A", "a.pdf", 2, 0, "A_PAGE_TWO"),
                PaperChunk("b", "Paper B", "b.pdf", 1, 0, "B_PAGE_ONE"),
            ]
        )
        result = PaperAgent(index).run(
            "read_full_papers", titles=["Paper A"], evidence_token_budget=1000
        )
        self.assertIn("全文已读", result)
        self.assertIn("A_PAGE_ONE", result)
        self.assertIn("A_PAGE_TWO", result)
        self.assertIn("all 2 indexed text pages", result)

        skipped = PaperAgent(index).run(
            "read_full_papers", titles=["Paper A"], evidence_token_budget=1
        )
        self.assertIn("预算不足，本轮未读", skipped)
        self.assertNotIn("A_PAGE_ONE", skipped)

    def test_registry_validates_required_arguments(self) -> None:
        registry = ToolRegistry()
        registry.register("echo", lambda value: value, {"value"})
        with self.assertRaisesRegex(ValueError, "missing required parameters"):
            registry.call("echo")

    def test_index_rejects_invalid_chunk_settings(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "chunk_size"):
                PaperIndex.build(Path(directory), chunk_size=100, overlap=0)


if __name__ == "__main__":
    unittest.main()
