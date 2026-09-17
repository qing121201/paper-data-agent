from __future__ import annotations

import os
from pathlib import Path

from .llm import LLMConfig


CONFIG_KEYS = (
    "PAPER_AGENT_BASE_URL",
    "PAPER_AGENT_API_KEY",
    "PAPER_AGENT_MODEL",
    "PAPER_AGENT_API_STYLE",
    "PAPER_AGENT_TIMEOUT",
    "PAPER_AGENT_MAX_OUTPUT_TOKENS",
)


def load_local_config(path: Path) -> None:
    """Load the small project-local dotenv subset without extra dependencies."""
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key in CONFIG_KEYS:
            os.environ.setdefault(key, value.strip().strip('"\''))


def apply_config(config: LLMConfig) -> None:
    os.environ["PAPER_AGENT_BASE_URL"] = config.base_url
    os.environ["PAPER_AGENT_API_KEY"] = config.api_key
    os.environ["PAPER_AGENT_MODEL"] = config.model
    os.environ["PAPER_AGENT_API_STYLE"] = config.api_style
    os.environ["PAPER_AGENT_TIMEOUT"] = str(config.timeout_seconds)
    os.environ["PAPER_AGENT_MAX_OUTPUT_TOKENS"] = "" if config.max_output_tokens is None else str(config.max_output_tokens)


def save_config(path: Path, config: LLMConfig) -> None:
    values = {
        "PAPER_AGENT_BASE_URL": config.base_url,
        "PAPER_AGENT_API_KEY": config.api_key,
        "PAPER_AGENT_MODEL": config.model,
        "PAPER_AGENT_API_STYLE": config.api_style,
        "PAPER_AGENT_TIMEOUT": str(config.timeout_seconds),
        "PAPER_AGENT_MAX_OUTPUT_TOKENS": "" if config.max_output_tokens is None else str(config.max_output_tokens),
    }
    if any("\n" in value or "\r" in value for value in values.values()):
        raise ValueError("配置值不能包含换行")
    path.write_text(
        "# 仅保存在本机；不要发送或提交此文件。\n"
        + "\n".join(f"{key}={value}" for key, value in values.items())
        + "\n",
        encoding="utf-8",
    )


def llm_ready(config: LLMConfig) -> bool:
    if not config.model or not config.base_url.startswith(("http://", "https://")):
        return False
    if "api.openai.com" in config.base_url and not config.api_key:
        return False
    return True
