from __future__ import annotations

import json
from pathlib import Path


DEFAULT_THEME = "学术蓝"


def load_ui_settings(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {"theme": DEFAULT_THEME}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"theme": DEFAULT_THEME}
    theme = payload.get("theme")
    return {"theme": theme if isinstance(theme, str) and theme else DEFAULT_THEME}


def save_ui_settings(path: Path, settings: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

