"""Mind-map generation adapter."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from .common import AdapterResult, PROJECT_ROOT, WINDOWS_NO_WINDOW, normalize_mindmap_theme, slug as _slug


class MindmapAdapterMixin:
    """Render controlled Markdown mind maps."""

    def create_mindmap(
        self,
        markdown: str = "",
        markdown_path: str = "",
        title: str = "论文思维导图",
        theme: str = "air",
    ) -> AdapterResult:
        requested_theme = str(theme or "").lower().strip()
        theme, used_fallback = normalize_mindmap_theme(theme)
        run_dir = self.output_dir / _slug(title, "mindmap")
        run_dir.mkdir(parents=True)
        if markdown_path:
            source = Path(markdown_path).expanduser().resolve()
            if not source.is_file():
                raise ValueError(f"思维导图 Markdown 不存在：{source}")
            content = source.read_text(encoding="utf-8")
        else:
            content = markdown.strip()
        if not content:
            raise ValueError("思维导图需要 markdown 或 markdown_path")
        md_path = run_dir / "mindmap.md"
        md_path.write_text(content, encoding="utf-8")
        script = PROJECT_ROOT / "third_party" / "ai4s_skills" / "mindmap-render" / "scripts" / "generate_mindmap.py"
        completed = subprocess.run(
            [
                sys.executable, str(script), "--md", str(md_path),
                "--output-dir", str(run_dir), "--theme", theme, "--scale", "2",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=180,
            check=False,
            creationflags=WINDOWS_NO_WINDOW,
        )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout).strip()[-1200:]
            raise RuntimeError(f"思维导图生成失败：{detail}")
        files = [str(path) for path in sorted(run_dir.iterdir()) if path.suffix.lower() in {".md", ".html", ".png", ".pdf"}]
        fallback_note = "" if not used_fallback else f"（请求主题 {requested_theme or '空值'} 已自动映射/回退）"
        return AdapterResult("create_mindmap", f"已生成 {theme} 主题思维导图。{fallback_note}", files)
