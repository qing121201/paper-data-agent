"""Shared values and result objects for controlled tool adapters."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
import subprocess


PROJECT_ROOT = Path(__file__).resolve().parents[2]
WINDOWS_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def slug(text: str, fallback: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff._-]+", "-", text).strip("-.")
    return (cleaned[:60] or fallback) + "-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f")


def normalize_mindmap_theme(theme: str) -> tuple[str, bool]:
    """Return a renderer-supported theme and whether a fallback/mapping occurred."""
    aliases = {
        "": "air", "default": "air", "默认": "air", "light": "air", "blue": "air",
        "paper": "editorial", "论文": "editorial", "night": "midnight", "dark": "midnight",
        "夜间": "midnight", "simple": "zen", "简洁": "zen",
    }
    requested = str(theme or "").lower().strip()
    normalized = aliases.get(requested, requested)
    if normalized not in {"air", "editorial", "midnight", "zen"}:
        normalized = "air"
    return normalized, normalized != requested


@dataclass(slots=True)
class AdapterResult:
    tool: str
    summary: str
    files: list[str]
    data: Any = None

    def as_markdown(self) -> str:
        lines = [f"# Tool result: {self.tool}", "", self.summary]
        if self.files:
            lines.extend(["", "## Generated files", *[f"- `{item}`" for item in self.files]])
        if self.data is not None:
            lines.extend(["", "## Structured result", "", "```json", json.dumps(self.data, ensure_ascii=False, indent=2), "```"])
        return "\n".join(lines)
