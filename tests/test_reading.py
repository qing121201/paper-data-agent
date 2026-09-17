import unittest

from paper_data_agent.core import PaperChunk
from paper_data_agent.reading import (
    abstract_or_front_pages,
    build_documents,
    full_page_unit,
    select_with_budget,
)


class ReadingPlanTests(unittest.TestCase):
    def test_reconstructs_overlapping_chunks_into_one_complete_page(self) -> None:
        overlap = "shared overlap segment longer than twenty characters"
        chunks = [
            PaperChunk("a", "Paper A", "a.pdf", 1, 0, f"alpha beta {overlap}"),
            PaperChunk("a", "Paper A", "a.pdf", 1, 1, f"{overlap} gamma delta"),
        ]
        page = build_documents(chunks)[0].pages[1]
        self.assertEqual(page, f"alpha beta {overlap} gamma delta")

    def test_reads_complete_abstract_until_introduction_boundary(self) -> None:
        abstract = "This paper studies research agents and evaluates their evidence coverage. " * 3
        chunks = [
            PaperChunk("a", "Paper A", "a.pdf", 1, 0, f"Title Authors Abstract {abstract} 1 Introduction body"),
        ]
        unit = abstract_or_front_pages(build_documents(chunks)[0])
        self.assertEqual(unit.unit, "complete_abstract")
        self.assertIn("evaluates their evidence coverage", unit.text)
        self.assertNotIn("Introduction body", unit.text)

    def test_fallback_reads_whole_front_pages_not_a_fixed_fragment(self) -> None:
        first = "front page content " * 100
        second = "second page content " * 100
        chunks = [
            PaperChunk("a", "Paper A", "a.pdf", 1, 0, first),
            PaperChunk("a", "Paper A", "a.pdf", 2, 0, second),
        ]
        unit = abstract_or_front_pages(build_documents(chunks)[0])
        self.assertEqual(unit.unit, "complete_front_pages")
        self.assertIn(first.strip(), unit.text)
        self.assertIn(second.strip(), unit.text)

    def test_budget_never_partially_includes_a_reading_unit(self) -> None:
        documents = build_documents([
            PaperChunk("a", "Paper A", "a.pdf", 1, 0, "alpha " * 100),
            PaperChunk("b", "Paper B", "b.pdf", 1, 0, "beta " * 100),
        ])
        units = [full_page_unit(item, 1, "test") for item in documents]
        selected, skipped, used = select_with_budget(units, units[0].estimated_tokens)
        self.assertEqual(len(selected), 1)
        self.assertEqual(len(skipped), 1)
        self.assertEqual(used, selected[0].estimated_tokens)
        self.assertEqual(selected[0].text, documents[0].pages[1])


if __name__ == "__main__":
    unittest.main()
