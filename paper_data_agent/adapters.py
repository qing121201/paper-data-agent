from __future__ import annotations

import json
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _slug(text: str, fallback: str) -> str:
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


class ResearchToolAdapters:
    """Controlled executable adapters used by the standalone paper agent."""

    def __init__(self, output_dir: Path):
        self.output_dir = output_dir.resolve()
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def _online_search_one(self, query: str, top_k: int = 8, year_from: int | None = None) -> list[dict[str, Any]]:
        if not query.strip():
            raise ValueError("在线检索需要非空查询词")
        limit = min(max(int(top_k), 1), 40)
        script = PROJECT_ROOT / "third_party" / "nature_skills" / "nature-academic-search" / "scripts" / "academic_search.py"
        command = [sys.executable, str(script), query.strip(), "--limit", str(limit)]
        if year_from:
            command.extend(["--year-from", str(int(year_from))])
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            check=False,
        )
        if completed.returncode == 0:
            papers = json.loads(completed.stdout)
        else:
            # Some Windows machines have a stale WinINET/Python proxy while
            # curl can still connect directly. Keep this fallback explicit and
            # read-only instead of changing the user's global proxy settings.
            candidate_limit = min(max(limit * 5, 20), 100)
            params = {"search": query.strip(), "per_page": candidate_limit, "mailto": "paper-agent@example.invalid"}
            if year_from:
                params["filter"] = f"from_publication_date:{int(year_from)}-01-01"
            url = "https://api.openalex.org/works?" + urlencode(params)
            fallback = subprocess.run(
                ["curl.exe", "--proxy", "", "--silent", "--show-error", "--max-time", "45", url],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=50,
                check=False,
            )
            if fallback.returncode != 0:
                detail = (fallback.stderr or completed.stderr or completed.stdout).strip()[:600]
                raise RuntimeError(f"OpenAlex 在线检索失败：{detail}")
            raw = json.loads(fallback.stdout)
            candidates = []
            query_terms = {
                term for term in re.findall(r"[A-Za-z0-9]+", query.lower())
                if len(term) > 2 and term not in {"paper", "papers", "about", "with", "from"}
            }
            for item in raw.get("results", []):
                authors = [
                    part.get("author", {}).get("display_name", "")
                    for part in item.get("authorships", [])[:12]
                ]
                location = item.get("best_oa_location") or item.get("primary_location") or {}
                public_urls = []
                for candidate_location in [item.get("best_oa_location"), item.get("primary_location"), *(item.get("locations") or [])]:
                    if not isinstance(candidate_location, dict):
                        continue
                    for candidate_url in (candidate_location.get("pdf_url"), candidate_location.get("landing_page_url")):
                        if candidate_url and candidate_url not in public_urls:
                            public_urls.append(candidate_url)
                paper = {
                    "title": item.get("display_name") or item.get("title"),
                    "year": item.get("publication_year"),
                    "doi": item.get("doi"),
                    "authors": [name for name in authors if name],
                    "cited_by_count": item.get("cited_by_count", 0),
                    "open_access_url": location.get("pdf_url") or location.get("landing_page_url"),
                    "open_access_urls": public_urls,
                    "openalex_id": item.get("id"),
                    "abstract": self._reconstruct_openalex_abstract(item),
                }
                title_terms = set(re.findall(r"[A-Za-z0-9]+", str(paper["title"]).lower()))
                overlap = len(query_terms & title_terms)
                candidates.append((overlap, int(paper["cited_by_count"] or 0), paper))
            candidates.sort(key=lambda row: (row[0], row[1]), reverse=True)
            papers = [paper for _overlap, _citations, paper in candidates[:limit]]
        if not isinstance(papers, list):
            raise RuntimeError("OpenAlex 返回格式异常")
        return papers

    @staticmethod
    def _reconstruct_openalex_abstract(item: dict[str, Any]) -> str:
        inverted = item.get("abstract_inverted_index")
        if not isinstance(inverted, dict):
            return ""
        positions: list[tuple[int, str]] = []
        for word, indexes in inverted.items():
            if isinstance(indexes, list):
                positions.extend((int(index), str(word)) for index in indexes)
        positions.sort()
        return " ".join(word for _index, word in positions)

    def online_search(
        self,
        query: str,
        top_k: int = 8,
        queries: list[str] | None = None,
        year_from: int | None = None,
    ) -> AdapterResult:
        query_list: list[str] = []
        for item in [*(queries or []), query]:
            value = str(item).strip()
            if value and value.lower() not in {existing.lower() for existing in query_list}:
                query_list.append(value)
        query_list = query_list[:4]
        if not query_list:
            raise ValueError("在线检索需要至少一个查询词")
        per_query = min(max(int(top_k), 1), 40)
        merged: dict[str, dict[str, Any]] = {}
        for search_query in query_list:
            for paper in self._online_search_one(search_query, per_query, year_from=year_from):
                key = str(paper.get("doi") or paper.get("openalex_id") or paper.get("title") or "").lower()
                if not key:
                    continue
                if key not in merged:
                    paper["matched_queries"] = [search_query]
                    paper["abstract_complete"] = bool(paper.get("abstract"))
                    merged[key] = paper
                elif search_query not in merged[key]["matched_queries"]:
                    merged[key]["matched_queries"].append(search_query)
        papers = sorted(
            merged.values(),
            key=lambda item: (
                len(item.get("matched_queries", [])),
                item.get("relevance_score") or 0,
                item.get("cited_by_count") or 0,
            ),
            reverse=True,
        )
        lines = [
            f"执行 {len(query_list)} 个独立 OpenAlex 查询，去重后得到 {len(papers)} 篇候选论文。",
            (f"年份范围：{year_from} 年至今。" if year_from else "年份范围：未限制。"),
            f"每个查询最多取相关度排序前 {per_query} 条；这是候选集，不代表领域里只有这些论文。",
            "在线阅读范围：题名、作者、年份、DOI、来源字段，以及 OpenAlex 提供时的完整索引摘要；未下载全文。",
            "",
            "查询计划：",
            *[f"- {item}" for item in query_list],
            "",
        ]
        for index, paper in enumerate(papers, start=1):
            title = paper.get("title") or "Untitled"
            year = paper.get("year") or "?"
            doi = paper.get("doi") or ""
            matched = "; ".join(paper.get("matched_queries", []))
            abstract_scope = "完整 OpenAlex 摘要" if paper.get("abstract_complete") else "无摘要，仅元数据"
            lines.append(
                f"{index}. {title} ({year})" + (f" — {doi}" if doi else "")
                + f" — {abstract_scope} — 命中查询：{matched}"
            )
        return AdapterResult("online_search", "\n".join(lines), [], papers)

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
        )
        files = [str(pptx_path), str(spec_path)]
        if audit_path.is_file():
            files.append(str(audit_path))
        summary = f"已生成 {len(normalized) + 1} 页可编辑 PPTX。"
        if audit.returncode != 0:
            summary += " 自动结构检查发现需人工复核的项目，详见 QA 输出。"
        return AdapterResult("create_presentation", summary, files)
