from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from .tool_adapters import (
    AcademicSearchMixin,
    AdapterResult,
    PROJECT_ROOT,
    WINDOWS_NO_WINDOW,
    normalize_mindmap_theme,
    slug as _slug,
)


class ResearchToolAdapters(AcademicSearchMixin):
    """Controlled executable adapters used by the standalone paper agent."""

    def __init__(self, output_dir: Path):
        self.output_dir = output_dir.resolve()
        self.output_dir.mkdir(parents=True, exist_ok=True)

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

    def create_scientific_figure(
        self,
        data_path: str,
        title: str = "Scientific figure",
        chart_type: str = "auto",
        x_column: str = "",
        y_columns: list[str] | None = None,
    ) -> AdapterResult:
        source = Path(data_path).expanduser().resolve()
        if not source.is_file():
            raise ValueError(f"数据文件不存在：{source}")
        if source.suffix.lower() not in {".csv", ".tsv"}:
            raise ValueError("当前科研绘图适配器先支持 CSV/TSV；Excel 可先另存为 CSV")

        import matplotlib.pyplot as plt
        import pandas as pd

        separator = "\t" if source.suffix.lower() == ".tsv" else ","
        frame = pd.read_csv(source, sep=separator)
        if frame.empty or len(frame.columns) < 1:
            raise ValueError("数据文件为空")
        numeric = list(frame.select_dtypes(include="number").columns)
        if not numeric:
            raise ValueError("没有找到可绘制的数值列")
        x_name = x_column if x_column in frame.columns else str(frame.columns[0])
        requested_y = [item for item in (y_columns or []) if item in numeric and item != x_name]
        y_names = requested_y or [item for item in numeric if item != x_name][:4]
        if not y_names:
            y_names = [numeric[0]]
        kind = chart_type.lower()
        if kind == "auto":
            kind = "line" if pd.api.types.is_numeric_dtype(frame[x_name]) else "bar"
        if kind not in {"line", "bar", "scatter", "hist"}:
            raise ValueError("chart_type 仅支持 auto、line、bar、scatter、hist")

        run_dir = self.output_dir / _slug(title, "figure")
        run_dir.mkdir(parents=True)
        fig, ax = plt.subplots(figsize=(8.6, 5.2), constrained_layout=True)
        palette = ["#245B8A", "#C45A3D", "#3B7F65", "#7A5AA6"]
        if kind == "hist":
            for idx, name in enumerate(y_names):
                ax.hist(frame[name].dropna(), bins=20, alpha=0.55, label=name, color=palette[idx % len(palette)])
        elif kind == "scatter":
            for idx, name in enumerate(y_names):
                ax.scatter(frame[x_name], frame[name], s=30, alpha=0.8, label=name, color=palette[idx % len(palette)])
        elif kind == "bar":
            frame.plot(x=x_name, y=y_names, kind="bar", ax=ax, color=palette[: len(y_names)], width=0.78)
        else:
            frame.plot(x=x_name, y=y_names, kind="line", ax=ax, color=palette[: len(y_names)], marker="o", linewidth=1.8)
        ax.set_title(title, loc="left", fontweight="bold")
        ax.spines[["top", "right"]].set_visible(False)
        ax.grid(axis="y", alpha=0.22)
        if len(y_names) > 1 or kind == "hist":
            ax.legend(frameon=False)
        png_path = run_dir / "figure.png"
        pdf_path = run_dir / "figure.pdf"
        fig.savefig(png_path, dpi=300, bbox_inches="tight")
        fig.savefig(pdf_path, bbox_inches="tight")
        plt.close(fig)
        manifest = {
            "source": str(source),
            "chart_type": kind,
            "x_column": x_name,
            "y_columns": y_names,
            "rows": len(frame),
            "generated_at": datetime.now().isoformat(),
        }
        manifest_path = run_dir / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        files = [str(png_path), str(pdf_path), str(manifest_path)]
        return AdapterResult("create_scientific_figure", f"已用 {len(frame)} 行数据生成 {kind} 科研图。", files, manifest)

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
        from .paper_visuals import LAYOUTS
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
