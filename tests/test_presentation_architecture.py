import unittest

from paper_data_agent import paper_visuals
from paper_data_agent import presentation_workspace
from paper_data_agent.presentation import assets, drawings, models, workspace


class PresentationArchitectureTests(unittest.TestCase):
    def test_visual_compatibility_facade_reexports_focused_modules(self) -> None:
        self.assertIs(paper_visuals.collect_assets, assets.collect_assets)
        self.assertIs(paper_visuals.resolve_images, assets.resolve_images)
        self.assertIs(paper_visuals.draw_visual, drawings.draw_visual)
        self.assertIs(paper_visuals.LAYOUTS, models.LAYOUTS)

    def test_drawings_do_not_import_pdf_retrieval(self) -> None:
        self.assertNotIn("fitz", drawings.__dict__)
        self.assertNotIn("PaperIndex", drawings.__dict__)

    def test_workspace_compatibility_facade_reexports_domain_functions(self) -> None:
        self.assertIs(presentation_workspace.load_spec, workspace.load_spec)
        self.assertIs(presentation_workspace.replace_slide, workspace.replace_slide)
        self.assertIs(presentation_workspace.render_preview, workspace.render_preview)
        self.assertIs(presentation_workspace.revise_slide, workspace.revise_slide)


if __name__ == "__main__":
    unittest.main()
