from pathlib import Path
import tempfile
import unittest

from paper_data_agent.providers import PROVIDER_BY_NAME, detect_provider
from paper_data_agent.ui_settings import DEFAULT_THEME, load_ui_settings, save_ui_settings


class ProviderPresetTests(unittest.TestCase):
    def test_domestic_presets_have_editable_compatible_endpoints(self) -> None:
        expected = {
            "DeepSeek": "https://api.deepseek.com",
            "Kimi（Moonshot）": "https://api.moonshot.cn/v1",
            "通义千问（阿里云百炼）": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "智谱 GLM": "https://open.bigmodel.cn/api/paas/v4",
        }
        for name, base_url in expected.items():
            with self.subTest(name=name):
                preset = PROVIDER_BY_NAME[name]
                self.assertEqual(preset.base_url, base_url)
                self.assertEqual(preset.api_style, "chat_completions")
                self.assertTrue(preset.model)
                self.assertIn(preset.model, preset.model_options)

    def test_deepseek_and_kimi_common_models_are_available(self) -> None:
        self.assertEqual(
            PROVIDER_BY_NAME["DeepSeek"].model_options,
            ("deepseek-flash", "deepseek-v4-pro"),
        )
        self.assertIn("kimi-k3", PROVIDER_BY_NAME["Kimi（Moonshot）"].model_options)
        self.assertIn("kimi-k2.6", PROVIDER_BY_NAME["Kimi（Moonshot）"].model_options)

    def test_provider_detection_and_custom_fallback(self) -> None:
        self.assertEqual(detect_provider("https://api.deepseek.com/").name, "DeepSeek")
        self.assertEqual(detect_provider("https://example.test/v1").name, "自定义 OpenAI 兼容接口")


class UISettingsTests(unittest.TestCase):
    def test_missing_or_invalid_settings_use_default(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ui.json"
            self.assertEqual(load_ui_settings(path)["theme"], DEFAULT_THEME)
            path.write_text("not-json", encoding="utf-8")
            self.assertEqual(load_ui_settings(path)["theme"], DEFAULT_THEME)

    def test_theme_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config" / "ui.json"
            save_ui_settings(path, {"theme": "深色夜读"})
            self.assertEqual(load_ui_settings(path), {"theme": "深色夜读"})


if __name__ == "__main__":
    unittest.main()
