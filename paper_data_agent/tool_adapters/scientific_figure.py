"""Scientific chart generation adapter."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from .common import AdapterResult, slug as _slug


class ScientificFigureAdapterMixin:
    """Generate charts from local CSV or TSV data."""

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
