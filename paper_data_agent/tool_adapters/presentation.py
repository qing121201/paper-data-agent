"""Editable PowerPoint generation adapter."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from .common import AdapterResult, PROJECT_ROOT, WINDOWS_NO_WINDOW, slug as _slug


class PresentationAdapterMixin:
    """Generate and audit editable PowerPoint presentations."""

    def create_presentation(self, spec: dict[str, Any]) -> AdapterResult:
        title = str(spec.get("title") or "论文汇报")[:160]
        slides = spec.get("slides")
        if not isinstance(slides, list) or not slides:
            raise ValueError("PPT 规格必须包含至少一页 slides")
        normalized: list[dict[str, Any]] = []
        for slide in slides[:24]:
            if not isinstance(slide, dict):
                continue
            bullets = slide.get("bullets") if isinstance(slide.get("bullets"), list) else []
            normalized.append(
                {
                    "title": str(slide.get("title") or "")[:120],
                    "bullets": [str(item)[:320] for item in bullets[:7]],
                    "source": str(slide.get("source") or "")[:260],
                    "layout": slide.get("layout", "image_right" if slide.get("images") else "text"),
                    "images": slide.get("images", []),
                }
            )
        if not normalized:
            raise ValueError("PPT 规格中没有有效页面")
        run_dir = self.output_dir / _slug(title, "presentation")
        run_dir.mkdir(parents=True)
        import shutil
        from PIL import Image
        from ..paper_visuals import LAYOUTS
        for number, slide in enumerate(normalized):
            if slide["layout"] not in LAYOUTS:
                raise ValueError("未知 PPT 布局")
            if not isinstance(slide["images"], list) or len(slide["images"]) > 2:
                raise ValueError("每页最多两张图片")
            copied = []
            for position, item in enumerate(slide["images"]):
                source = Path(item["path"])
                with Image.open(source) as picture:
                    picture.verify()
                assets_dir = run_dir / "assets"
                assets_dir.mkdir(exist_ok=True)
                destination = assets_dir / f"slide-{number + 1}-{position + 1}{source.suffix.lower()}"
                shutil.copy2(source, destination)
                copied.append({**item, "path": str(destination.resolve())})
            slide["images"] = copied
            if not copied:
                slide["layout"] = "text"
        normalized_spec = {
            "title": title,
            "subtitle": str(spec.get("subtitle") or "论文 Data Agent 生成")[:160],
            "slides": normalized,
        }
        spec_path = run_dir / "presentation_spec.json"
        spec_path.write_text(json.dumps(normalized_spec, ensure_ascii=False, indent=2), encoding="utf-8")
        pptx_path = run_dir / "paper-presentation.pptx"
        script = PROJECT_ROOT / "scripts" / "create_presentation.ps1"
        completed = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script),
                "-SpecPath",
                str(spec_path),
                "-OutputPath",
                str(pptx_path),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
            check=False,
            creationflags=WINDOWS_NO_WINDOW,
        )
        if completed.returncode != 0 or not pptx_path.is_file():
            detail = (completed.stderr or completed.stdout).strip()[:800]
            raise RuntimeError(f"PowerPoint 生成失败：{detail}")
        audit_script = PROJECT_ROOT / "third_party" / "nature_skills" / "nature-paper2ppt" / "scripts" / "audit_pptx_quality.py"
        audit_path = run_dir / "qa_report.json"
        audit = subprocess.run(
            [sys.executable, str(audit_script), str(pptx_path), "--json", str(audit_path)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            check=False,
            creationflags=WINDOWS_NO_WINDOW,
        )
        files = [str(pptx_path), str(spec_path)]
        if audit_path.is_file():
            files.append(str(audit_path))
        summary = f"已生成 {len(normalized) + 1} 页可编辑 PPTX。"
        if audit.returncode != 0:
            summary += " 自动结构检查发现需人工复核的项目，详见 QA 输出。"
        return AdapterResult("create_presentation", summary, files)
