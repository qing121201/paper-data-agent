"""Render validated declarative flowcharts and data charts without code execution."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import textwrap


def draw_visual(spec: dict, output: Path) -> dict:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import FancyBboxPatch

    if not isinstance(spec, dict) or spec.get("kind") not in {"flow", "bar", "line"}:
        raise ValueError("自绘图仅支持 flow、bar、line")
    source = str(spec.get("source", "")).strip()
    if not source:
        raise ValueError("自绘图必须注明依据或数据来源")
    kind = spec["kind"]
    if kind == "flow":
        nodes = spec.get("nodes", [])
        if not isinstance(nodes, list) or not 2 <= len(nodes) <= 6 or not all(
            isinstance(node, str) and len(node) <= 60 for node in nodes
        ):
            raise ValueError("流程图需要 2–6 个简短步骤")
    else:
        labels, values = spec.get("labels", []), spec.get("values", [])
        if (
            not isinstance(labels, list) or not isinstance(values, list)
            or not 2 <= len(labels) <= 12 or len(labels) != len(values)
            or not all(isinstance(label, str) and len(label) <= 50 for label in labels)
            or not all(type(value) in (int, float) and math.isfinite(value) for value in values)
        ):
            raise ValueError("数据图需要 2–12 组有限数值和对应标签")
    output.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(json.dumps(spec, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:20]
    path = output / f"drawing-{digest}.png"
    with plt.rc_context({
        "font.sans-serif": ["Microsoft YaHei", "SimHei", "DejaVu Sans"],
        "axes.unicode_minus": False,
    }):
        figure, axes = plt.subplots(figsize=(10, 5.5), constrained_layout=True)
        try:
            axes.set_title(str(spec.get("title", "")), fontsize=17, loc="left", pad=22)
            if kind == "flow":
                _draw_flow(axes, nodes, FancyBboxPatch)
            else:
                _draw_series(axes, kind, labels, values, str(spec.get("ylabel", "")))
            figure.savefig(path, dpi=190, facecolor="white")
            figure.savefig(path.with_suffix(".svg"), facecolor="white")
        finally:
            plt.close(figure)
    path.with_suffix(".json").write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "asset_id": digest,
        "path": str(path.resolve()),
        "kind": "drawn_chart",
        "title": spec.get("title", ""),
        "source": "根据原文整理绘制：" + source,
        "drawing_spec": spec,
    }


def _draw_flow(axes, nodes: list[str], box_patch) -> None:
    axes.set_xlim(0, 10)
    axes.set_ylim(0, 5)
    axes.axis("off")
    columns = len(nodes) if len(nodes) <= 3 else 3
    width = 9 / columns - .5
    locations = []
    for index, node in enumerate(nodes):
        row, column = divmod(index, columns)
        if row == 1:
            column = columns - 1 - column
        x = .5 + column * (9 / columns)
        y = 1.7 if len(nodes) <= 3 else 3.0 - row * 2.3
        locations.append((x, y))
        axes.add_patch(box_patch(
            (x, y), width, 1.5, boxstyle="round,pad=0.05",
            facecolor="#e8f1fa", edgecolor="#245b8a",
        ))
        axes.text(x + width / 2, y + .75, textwrap.fill(node, 10), ha="center", va="center", fontsize=14)
    for (x, y), (next_x, next_y) in zip(locations, locations[1:]):
        if next_y != y:
            start, end = (x + width / 2, y - .08), (next_x + width / 2, next_y + 1.58)
        elif next_x > x:
            start, end = (x + width + .07, y + .75), (next_x - .07, next_y + .75)
        else:
            start, end = (x - .07, y + .75), (next_x + width + .07, next_y + .75)
        axes.annotate("", xy=end, xytext=start, arrowprops={"arrowstyle": "->", "color": "#245b8a", "lw": 1.8})


def _draw_series(axes, kind: str, labels: list[str], values: list[float], ylabel: str) -> None:
    positions = list(range(len(labels)))
    if kind == "bar":
        axes.bar(positions, values, color="#397aaa", width=.6)
    else:
        axes.plot(positions, values, color="#397aaa", marker="o", linewidth=2)
    axes.set_xticks(positions, [textwrap.fill(label, 12) for label in labels], fontsize=10)
    axes.set_ylabel(ylabel)
    axes.spines[["top", "right"]].set_visible(False)
    axes.grid(axis="y", alpha=.18)
    for x, y in zip(positions, values):
        axes.annotate(f"{y:g}", (x, y), xytext=(0, 7), textcoords="offset points", ha="center")
    axes.margins(y=.18)
