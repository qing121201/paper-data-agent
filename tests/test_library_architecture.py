import unittest

from paper_data_agent import library
from paper_data_agent.library_domain import manager, models, repository
from paper_data_agent.library_domain.online_import import OnlineImportMixin


class LibraryArchitectureTests(unittest.TestCase):
    def test_compatibility_facade_reexports_domain_types(self) -> None:
        self.assertIs(library.LibraryManager, manager.LibraryManager)
        self.assertIs(library.PaperLibrary, repository.PaperLibrary)
        self.assertIs(library.PaperRecord, models.PaperRecord)
        self.assertIs(library.ImportResult, models.ImportResult)
        self.assertIs(library.SearchImportResult, models.SearchImportResult)

    def test_repository_composes_online_import_without_ui_dependency(self) -> None:
        self.assertTrue(issubclass(repository.PaperLibrary, OnlineImportMixin))
        self.assertNotIn("tkinter", repository.__dict__)
        self.assertNotIn("tkinter", manager.__dict__)


if __name__ == "__main__":
    unittest.main()
