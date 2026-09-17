from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from PIL import Image
from paper_data_agent.paper_visuals import resolve_images, draw_visual
from paper_data_agent.presentation_workspace import replace_slide
from paper_data_agent.llm import LLMConfig, OpenAICompatibleClient


class VisualTests(unittest.TestCase):
    def test_reject_unknown_assets_and_bad_crops(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ValueError):
                resolve_images({"images": [{"asset_id": "invented"}]}, [], Path(folder))
            asset = {"asset_id": "known", "path": "unused.png", "kind": "pdf_page"}
            with self.assertRaises(ValueError):
                resolve_images({"images": [{"asset_id": "known", "crop": [0, 0, -1, 1]}]}, [asset], Path(folder))

    def test_text_revision_keeps_images_and_other_slides(self):
        spec = {"slides": [{"title": "旧", "images": [{"path": "original.png"}], "layout": "image_right"}, {"title": "不动"}]}
        updated = replace_slide(spec, 1, {"title": "新"})
        self.assertEqual(updated["slides"][0]["images"], spec["slides"][0]["images"])
        self.assertEqual(updated["slides"][1], spec["slides"][1])

    def test_chart_requires_source_and_finite_real_values(self):
        with tempfile.TemporaryDirectory() as folder:
            for spec in ({"kind": "bar"}, {"kind": "bar", "source": "test", "labels": ["a", "b"], "values": [1, float("nan")]}):
                with self.assertRaises(ValueError):
                    draw_visual(spec, Path(folder))

    def test_drawing_produces_image_and_auditable_spec(self):
        with tempfile.TemporaryDirectory() as folder:
            result = resolve_images({"drawing": {"kind": "flow", "nodes": ["Read", "Test"], "source": "test fixture"}}, [], Path(folder))
            image = Path(result["images"][0]["path"])
            self.assertTrue(image.is_file())
            self.assertTrue(image.with_suffix(".json").is_file())
            self.assertEqual(result["layout"], "image_right")

    def test_multimodal_payloads(self):
        with tempfile.TemporaryDirectory() as folder:
            image = Path(folder) / "test.png"
            Image.new("RGB", (8, 8), "white").save(image)
            for style in ("chat_completions", "responses"):
                client = OpenAICompatibleClient(LLMConfig("http://localhost", "test", api_style=style))
                response = {"output_text": "ok"} if style == "responses" else {"choices": [{"message": {"content": "ok"}}]}
                with patch.object(client, "_post", return_value=response) as post:
                    self.assertEqual(client.generate("system", "user", image_paths=[str(image)]), "ok")
                    payload = post.call_args.args[1]
                    content = payload["input"][0]["content"] if style == "responses" else payload["messages"][1]["content"]
                    self.assertEqual(len(content), 2)

