import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from paper_data_agent.core import PaperChunk, PaperIndex
from paper_data_agent.library import ImportResult, LibraryManager
from paper_data_agent.web_sources import WINDOWS_NO_WINDOW, download_public_paper, probe_public_url


FAKE_PDF = b"%PDF-1.4\n% paper agent test fixture\n%%EOF\n"


class _PaperSite(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/paper":
            body = b'<html><head><meta name="citation_title" content="Test Paper"><meta name="citation_pdf_url" content="/paper.pdf"></head></html>'
            content_type = "text/html"
        else:
            body = FAKE_PDF
            content_type = "application/pdf"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        return


class PaperSite:
    def __enter__(self) -> str:
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _PaperSite)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        host, port = self.server.server_address
        return f"http://{host}:{port}"

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)


class WebSourceTests(unittest.TestCase):
    def test_probe_rejects_deleted_zenodo_tombstone_even_when_page_is_200(self) -> None:
        completed = SimpleNamespace(
            stdout=b'The record you are trying to access was removed from Zenodo. "removal_reason"',
            stderr=b"\n__PAPER_AGENT_PROBE__200\thttps://zenodo.org/api/records/123",
            returncode=0,
        )
        with patch("paper_data_agent.web_sources._validate_public_url"), patch(
            "paper_data_agent.web_sources.subprocess.run", return_value=completed
        ):
            status = probe_public_url("https://doi.org/10.5281/zenodo.123")
        self.assertFalse(status.available)

    def test_probe_keeps_live_public_page(self) -> None:
        completed = SimpleNamespace(
            stdout=b"<html><title>Paper</title></html>",
            stderr=b"\n__PAPER_AGENT_PROBE__200\thttps://example.org/paper",
            returncode=0,
        )
        with patch("paper_data_agent.web_sources._validate_public_url"), patch(
            "paper_data_agent.web_sources.subprocess.run", return_value=completed
        ) as runner:
            status = probe_public_url("https://example.org/paper")
        self.assertTrue(status.available)
        self.assertEqual(runner.call_args.kwargs["creationflags"], WINDOWS_NO_WINDOW)

    def test_download_direct_pdf_and_html_paper_page(self) -> None:
        with tempfile.TemporaryDirectory() as directory, PaperSite() as base_url:
            destination = Path(directory)
            direct = download_public_paper(f"{base_url}/direct.pdf", destination, allow_private=True)
            page = download_public_paper(f"{base_url}/paper", destination, allow_private=True)
            self.assertTrue(direct.path.is_file())
            self.assertEqual(page.title, "Test Paper")
            self.assertTrue(page.resolved_url.endswith("/paper.pdf"))
            self.assertEqual(page.path.read_bytes(), FAKE_PDF)

    def test_private_url_is_rejected_by_default(self) -> None:
        with self.assertRaisesRegex(ValueError, "公开网站"):
            download_public_paper("http://127.0.0.1/paper.pdf", Path("unused"))

    def test_known_publication_urls_are_normalized_before_download(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch(
            "paper_data_agent.web_sources._fetch",
            return_value=(FAKE_PDF, "https://www.nature.com/articles/example.pdf", "application/pdf"),
        ) as fetch:
            result = download_public_paper(
                "https://www.nature.com/articles/example_reference.pdf", Path(directory))
            self.assertTrue(result.path.is_file())
        self.assertEqual(fetch.call_args.args[0], "https://www.nature.com/articles/example.pdf")

    def test_pmc_pdf_challenge_falls_back_to_full_article_snapshot(self) -> None:
        challenge = b'<html><title>Preparing to download ...</title></html>'
        article = b'<html><head><meta name="citation_title" content="PMC Paper"></head><body>' + b'x' * 6000 + b'</body></html>'
        rendered = b"%PDF-1.4\nrendered article\n%%EOF\n"
        with tempfile.TemporaryDirectory() as directory, patch(
            "paper_data_agent.web_sources._fetch",
            side_effect=[(challenge, "https://pmc.ncbi.nlm.nih.gov/articles/PMC123/pdf/a.pdf", "text/html"),
                         (article, "https://pmc.ncbi.nlm.nih.gov/articles/PMC123/", "text/html")],
        ), patch("paper_data_agent.web_sources._render_public_html_pdf", return_value=rendered):
            result = download_public_paper(
                "https://pmc.ncbi.nlm.nih.gov/articles/PMC123/pdf/a.pdf", Path(directory))
            self.assertEqual(result.path.read_bytes(), rendered)
            self.assertEqual(result.resolved_url, "https://pmc.ncbi.nlm.nih.gov/articles/PMC123/")


class LibraryTests(unittest.TestCase):
    def test_search_and_import_reports_candidates_and_downloads(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            library = LibraryManager(Path(directory) / "libraries").create("课题")
            papers = [{"title": "Virtual Cell Open Paper", "open_access_url": "https://example.org/paper.pdf"},
                      {"title": "Virtual Cell Closed Paper", "open_access_url": None}]
            fake_import = ImportResult(1, 0, 0, [])
            with patch("paper_data_agent.adapters.ResearchToolAdapters.online_search",
                       return_value=SimpleNamespace(data=papers)), patch.object(library, "import_url", return_value=fake_import):
                result = library.search_and_import("virtual cell", 2)
            self.assertEqual((result.candidates, result.downloadable, result.added), (2, 1, 1))
            self.assertIn("Virtual Cell Open Paper", result.imported_titles)
            self.assertIn("未提供公开地址", result.failures[0])

    def test_search_and_import_prefers_repository_pdf_over_landing_pages(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            library = LibraryManager(Path(directory) / "libraries").create("课题")
            papers = [{
                "title": "Virtual Cell Paper",
                "abstract": "virtual cell model",
                "open_access_url": "https://doi.org/10.1/example",
                "open_access_urls": [
                    "https://doi.org/10.1/example",
                    "https://pubmed.ncbi.nlm.nih.gov/1/",
                    "https://arxiv.org/abs/2409.11654",
                ],
            }]
            fake_import = ImportResult(1, 0, 0, [])
            with patch("paper_data_agent.adapters.ResearchToolAdapters.online_search",
                       return_value=SimpleNamespace(data=papers)), patch.object(
                           library, "import_url", return_value=fake_import) as importer:
                result = library.search_and_import("virtual cell", 1)
            self.assertEqual(result.added, 1)
            self.assertEqual(importer.call_args.args[0], "https://arxiv.org/pdf/2409.11654")

    def test_search_and_import_uses_larger_pool_until_target_is_added(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            library = LibraryManager(Path(directory) / "libraries").create("课题")
            papers = [
                {
                    "title": f"Virtual Cell Paper {index}",
                    "abstract": "virtual cell model",
                    "cited_by_count": 100 - index,
                    "open_access_url": f"https://example.org/{index}.pdf",
                }
                for index in range(20)
            ]
            calls = []
            def fake_import(url: str, **_kwargs):
                calls.append(url)
                if len(calls) <= 2:
                    return ImportResult(0, 0, 1, ["download failed"])
                return ImportResult(1, 0, 0, [])
            with patch("paper_data_agent.adapters.ResearchToolAdapters.online_search",
                       return_value=SimpleNamespace(data=papers)) as search, patch.object(
                           library, "import_url", side_effect=fake_import):
                result = library.search_and_import("virtual cell", 5)
            self.assertEqual(result.candidates, 20)
            self.assertEqual(result.requested, 5)
            self.assertEqual(result.added, 5)
            self.assertEqual(len(calls), 7)
            self.assertEqual(search.call_args.kwargs["top_k"], 20)
            self.assertNotIn("关键原因", result.as_markdown())

    def test_search_import_result_keeps_public_bibliographic_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            library = LibraryManager(Path(directory) / "libraries").create("课题")
            papers = [{
                "title": "Virtual Cell Metadata Paper",
                "abstract": "virtual cell model",
                "authors": ["Alice Zhang", "Bo Li"],
                "year": 2025,
                "doi": "https://doi.org/10.1000/vcell.1",
                "cited_by_count": 42,
                "open_access_url": "https://example.org/paper.pdf",
            }]
            with patch("paper_data_agent.adapters.ResearchToolAdapters.online_search",
                       return_value=SimpleNamespace(data=papers)), patch.object(
                           library, "import_url", return_value=ImportResult(1, 0, 0, [])):
                result = library.search_and_import("virtual cell", 1)
            markdown = result.as_markdown()
            self.assertEqual(result.imported_details[0]["authors"], ["Alice Zhang", "Bo Li"])
            self.assertEqual(result.imported_details[0]["cited_by_count"], 42)
            self.assertIn("10.1000/vcell.1", markdown)
            self.assertIn("Alice Zhang、Bo Li", markdown)
            self.assertIn("| 42 |", markdown)

    def test_remove_paper_rebuilds_index_without_deleting_pdf(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "paper.pdf"
            source.write_bytes(FAKE_PDF)
            library = LibraryManager(root / "libraries").create("课题")
            fake_index = PaperIndex([PaperChunk("paper", "paper", str(source), 1, 0, "virtual cell")])
            with patch("paper_data_agent.library_domain.repository.PaperIndex.build_from_paths", return_value=fake_index):
                self.assertEqual(library.import_folder(root).added, 1)
            record = library.records()[0]
            removed = library.remove_paper(record.paper_id)
            self.assertEqual(removed.paper_id, record.paper_id)
            self.assertEqual(library.paper_count(), 0)
            self.assertFalse(library.index_path.exists())
            self.assertTrue(source.exists())
    def test_libraries_are_independent_and_folder_import_is_recursive(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source" / "nested"
            source.mkdir(parents=True)
            pdf = source / "paper.pdf"
            pdf.write_bytes(FAKE_PDF)
            manager = LibraryManager(root / "libraries")
            first = manager.create("课题 A")
            second = manager.create("课题 B")
            fake_index = PaperIndex(
                [PaperChunk("paper", "paper", str(pdf), 1, 0, "software engineering agent")]
            )
            with patch("paper_data_agent.library_domain.repository.PaperIndex.build_from_paths", return_value=fake_index):
                result = first.import_folder(root / "source")
            self.assertEqual(result.added, 1)
            self.assertEqual(first.paper_count(), 1)
            self.assertEqual(second.paper_count(), 0)
            self.assertTrue(first.index_path.is_file())
            metadata = json.loads((first.path / "library.json").read_text(encoding="utf-8"))
            self.assertEqual(metadata["name"], "课题 A")

    def test_clear_chat_archives_session_without_touching_library_data(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            library = LibraryManager(Path(directory) / "libraries").create("课题")
            latest = library.sessions_path / "latest.json"
            checkpoint = library.sessions_path / "in_progress.json"
            latest.write_text('{"messages": [{"role": "user", "content": "hello"}]}', encoding="utf-8")
            checkpoint.write_text('{"status": "interrupted"}', encoding="utf-8")
            papers_before = library.papers_path.read_text(encoding="utf-8")

            archived = library.clear_chat_session()

            self.assertEqual(len(archived), 2)
            self.assertFalse(latest.exists())
            self.assertFalse(checkpoint.exists())
            self.assertTrue(all(path.is_file() for path in archived))
            self.assertEqual(library.papers_path.read_text(encoding="utf-8"), papers_before)


if __name__ == "__main__":
    unittest.main()
