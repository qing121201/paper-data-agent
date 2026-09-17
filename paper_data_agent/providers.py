from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ProviderPreset:
    """Editable defaults for an OpenAI-compatible model provider."""

    name: str
    base_url: str
    model: str
    model_options: tuple[str, ...] = ()
    api_style: str = "chat_completions"
    requires_key: bool = True
    note: str = ""


PROVIDER_PRESETS: tuple[ProviderPreset, ...] = (
    ProviderPreset(
        "DeepSeek",
        "https://api.deepseek.com",
        "deepseek-flash",
        ("deepseek-flash", "deepseek-v4-pro"),
        note="推荐 deepseek-flash（当前对应 V4.1 Flash）；V4 Pro 目前也会路由到 V4.1 Flash。",
    ),
    ProviderPreset(
        "Kimi（Moonshot）",
        "https://api.moonshot.cn/v1",
        "kimi-k3",
        (
            "kimi-k3", "kimi-k2.7-code-highspeed", "kimi-k2.7-code", "kimi-k2.6",
            "moonshot-v1-128k", "moonshot-v1-32k", "moonshot-v1-8k",
        ),
        note="Kimi 官方 OpenAI 兼容接口。",
    ),
    ProviderPreset(
        "通义千问（阿里云百炼）",
        "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "qwen-plus",
        ("qwen-plus", "qwen3.8-max", "qwen3.8-flash", "qwen3.7-plus", "qwen-flash", "qwen-long"),
        note="北京地域共享地址；专属业务空间可直接改写 Base URL。",
    ),
    ProviderPreset(
        "智谱 GLM",
        "https://open.bigmodel.cn/api/paas/v4",
        "glm-5.2",
        ("glm-5.2", "glm-5.1", "glm-5-turbo", "glm-5", "glm-4.7", "glm-4.7-flash"),
        note="智谱开放平台的 OpenAI 兼容接口。",
    ),
    ProviderPreset(
        "火山方舟（豆包）",
        "https://ark.cn-beijing.volces.com/api/v3",
        "doubao-seed-2-0-lite-260215",
        ("doubao-seed-2-0-lite-260215",),
        note="模型 ID 以方舟控制台中实际开通的模型或推理接入点为准。",
    ),
    ProviderPreset(
        "硅基流动",
        "https://api.siliconflow.cn/v1",
        "deepseek-ai/DeepSeek-V4-Flash",
        (
            "deepseek-ai/DeepSeek-V4-Flash",
            "Pro/moonshotai/Kimi-K2.6",
            "Pro/zai-org/GLM-5.1",
        ),
        note="聚合平台；可从模型广场复制其他完整模型 ID。",
    ),
    ProviderPreset(
        "OpenAI",
        "https://api.openai.com/v1",
        "gpt-5-mini",
        ("gpt-5-mini", "gpt-5", "gpt-4.1-mini", "gpt-4.1"),
        api_style="responses",
        note="OpenAI 官方接口。",
    ),
    ProviderPreset(
        "Ollama（本机）",
        "http://localhost:11434/v1",
        "qwen3:8b",
        ("qwen3:8b", "deepseek-r1:8b", "llama3.2:3b"),
        requires_key=False,
        note="需要先安装 Ollama 并下载对应模型；API Key 会被忽略。",
    ),
    ProviderPreset(
        "自定义 OpenAI 兼容接口",
        "",
        "",
        (),
        note="适用于其他兼容服务；请填写服务商给出的 Base URL 和模型 ID。",
    ),
)

PROVIDER_BY_NAME = {item.name: item for item in PROVIDER_PRESETS}


def detect_provider(base_url: str) -> ProviderPreset:
    normalized = base_url.rstrip("/").lower()
    for preset in PROVIDER_PRESETS:
        if preset.base_url and preset.base_url.rstrip("/").lower() == normalized:
            return preset
    return PROVIDER_BY_NAME["自定义 OpenAI 兼容接口"]
