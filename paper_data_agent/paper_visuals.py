"""Source-linked PDF page assets and constrained visual selection for slides."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re

LAYOUTS = {"text", "image_left", "image_right", "image_top", "image_full", "two_images"}
VISUAL_SCHEMA = """页面可含 layout: text/image_left/image_right/image_top/image_full/two_images，
images: [{asset_id: 候选图片ID, crop: [x0,y0,x1,y1], caption: 中文图注}]。
crop 是相对于整张候选图片的 0–1 坐标，可省略表示使用整页。依据所看到的图像裁剪，
保留坐标轴、图例、标签，不捏造图或裁剪掉影响结论的条件。每页最多 2 张。
图文页正文最多 3 个短要点；图较复杂选 image_full 或 image_top。不把整页论文截图冒充单独提取的原图。
只引用提供的 asset_id，禁止编造图片路径。实际来源由程序写入图注。
也可以用 drawing 自绘图表（不能与 images 同时填写）：
流程图 {kind:"flow",title:"方法流程",nodes:["步骤1","步骤2"],source:"论文名与页码"}，2–6 个顺序步骤，nodes 必须是字符串数组，每项不超过 30 字，不使用对象；
优先 3–4 个简洁步骤；用户指定三步就返回 3 个节点，不要把每个子步骤展开。节点避免长句，每个节点推荐不超过 16 字。
数据图 {kind:"bar"或"line",title:"指标对比",labels:["方法A","方法B"],
values:[1.2,2.3],ylabel:"指标及单位",source:"论文名、页码与表格号"}。
数值必须逐项来自提供的原文证据或用户数据；条件不同不能强行比较；无可靠数据改画流程图。
自绘图应明确标注根据原文整理，不冒充原论文图。
"""


def collect_assets(index, query: str, output: Path, limit: int = 8) -> list[dict]:
    """Rank PDFs by title/query, then render figure/table-bearing pages."""
    import fitz
    words = set(re.findall(r"[a-z0-9]+", query.lower()))
    documents = {}
    for chunk in index.chunks:
        documents.setdefault(chunk.path, chunk.title)
    ranked = sorted(documents.items(), key=lambda row: -sum(
        len(word) for word in words if len(word) > 2 and word in row[1].lower()))
    output.mkdir(parents=True, exist_ok=True)
    candidates = []
    for path, title in ranked[:4]:
        if not Path(path).is_file():
            continue
        with fitz.open(path) as pdf:
            pages = []
            for number in range(min(len(pdf), 35)):
                page = pdf[number]
                text = page.get_text()
                captions = re.findall(r"(?:Figure|Fig\.|Table)\s*\d+[^\n]*", text, re.I)
                if not captions:
                    continue
                # Prefer pages with actual visual material over pages merely citing figures.
                score = len(page.get_images()) * 2 + bool(page.get_drawings()) + len(captions)
                if re.search(r"(?im)^\s*(references|bibliography)\s*$", text):
                    score -= 30
                pages.append((score, number, captions))
            pages.sort(reverse=True)
            # Include a main-body figure, not only image-dense appendix pages.
            main = [entry for entry in pages if entry[1] < 8 and entry[0] > 0]
            selected = ([main[0]] if main else [])
            selected += [entry for entry in pages if entry not in selected][:2 - len(selected)]
            for _, number, captions in selected:
                page = pdf[number]
                digest = hashlib.sha256(f"{path}:{Path(path).stat().st_mtime_ns}:{number}".encode()).hexdigest()[:16]
                image = output / f"page-{digest}.png"
                if not image.exists():
                    page.get_pixmap(matrix=fitz.Matrix(1.8, 1.8), alpha=False).save(image)
                candidates.append({"asset_id": digest, "path": str(image.resolve()),
                                   "pdf_path": path, "title": title, "page": number + 1,
                                   "captions": captions[:6], "text": page.get_text(), "kind": "pdf_page"})
                if len(candidates) >= limit:
                    return candidates
    return candidates


def asset_prompt(assets: list[dict]) -> str:
    return "候选图片按下列顺序随请求发送：\n" + json.dumps(
        [{key: value for key, value in asset.items() if key not in {"path", "pdf_path"}} for asset in assets],
        ensure_ascii=False)


def collect_chart_assets(output_dir: Path, evidence: str) -> list[dict]:
    """Only expose chart artifacts explicitly present in this task's evidence."""
    assets = []
    for path in output_dir.glob("*/figure.png"):
        if str(path) not in evidence and str(path.resolve()) not in evidence:
            continue
        manifest_path = path.parent / "manifest.json"
        if not manifest_path.is_file():
            continue
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assets.append({"asset_id": hashlib.sha256(str(path.resolve()).encode()).hexdigest()[:16],
                       "path": str(path.resolve()), "kind": "data_chart",
                       "title": path.parent.name, "source": "数据文件：" + str(manifest.get("source", "")),
                       "captions": [str(manifest)]})
    return assets


def resolve_images(slide: dict, assets: list[dict], output: Path) -> dict:
    """Map model-selected IDs to local assets and provenance, rejecting invented paths."""
    result = deepcopy(slide)
    drawing = result.pop("drawing", None)
    if drawing:
        if result.get("images"):
            raise ValueError("请在这一页选择原图或自绘图，不要同时指定")
        asset = draw_visual(drawing, output)
        assets = [*assets, asset]
        result["images"] = [{"asset_id": asset["asset_id"], "caption": drawing.get("title", "")}]
    layout = result.get("layout", "text")
    if layout not in LAYOUTS:
        raise ValueError(f"未知图文布局：{layout}")
    items = result.get("images", [])
    if not isinstance(items, list) or len(items) > 2:
        raise ValueError("每页最多两张图片")
    known = {item["asset_id"]: item for item in assets}
    resolved = []
    for item in items:
        if not isinstance(item, dict) or item.get("asset_id") not in known:
            raise ValueError("模型选择了不存在的图片，请重试")
        asset = known[item["asset_id"]]
        image_path = Path(asset["path"])
        crop = item.get("crop")
        if crop is not None:
            if (not isinstance(crop, list) or len(crop) != 4 or
                not all(type(value) in (int, float) and 0 <= value <= 1 for value in crop) or
                crop[2] - crop[0] < .05 or crop[3] - crop[1] < .05):
                raise ValueError("图片裁剪坐标无效")
            if asset.get("kind") != "pdf_page":
                raise ValueError("数据图暂不支持裁剪，请保留完整坐标轴")
            import fitz
            digest = hashlib.sha256(json.dumps([asset["asset_id"], crop]).encode()).hexdigest()[:20]
            output.mkdir(parents=True, exist_ok=True)
            image_path = output / f"crop-{digest}.png"
            with fitz.open(asset["pdf_path"]) as pdf:
                page = pdf[asset["page"] - 1]
                rect = page.rect
                clip = fitz.Rect(rect.x0 + rect.width * crop[0], rect.y0 + rect.height * crop[1],
                                 rect.x0 + rect.width * crop[2], rect.y0 + rect.height * crop[3])
                # A model may identify only one panel of a composite figure. Snap the
                # crop to every substantial embedded panel crossing the same vertical
                # figure band, then add a small safety margin. This preserves labels,
                # arrows and the left/right panels instead of silently clipping evidence.
                substantial = []
                for info in page.get_image_info():
                    box = fitz.Rect(info["bbox"])
                    if box.width * box.height < rect.width * rect.height * .002:
                        continue
                    vertical_overlap = max(0, min(box.y1, clip.y1) - max(box.y0, clip.y0))
                    if vertical_overlap >= min(box.height, clip.height) * .35:
                        substantial.append(box)
                if substantial:
                    visual = substantial[0]
                    for box in substantial[1:]:
                        visual |= box
                    clip |= visual
                margin_x, margin_y = rect.width * .025, rect.height * .018
                clip = fitz.Rect(max(rect.x0, clip.x0 - margin_x), max(rect.y0, clip.y0 - margin_y),
                                 min(rect.x1, clip.x1 + margin_x), min(rect.y1, clip.y1 + margin_y))
                page.get_pixmap(matrix=fitz.Matrix(2, 2), clip=clip, alpha=False).save(image_path)
            effective_crop = [(clip.x0 - rect.x0) / rect.width, (clip.y0 - rect.y0) / rect.height,
                              (clip.x1 - rect.x0) / rect.width, (clip.y1 - rect.y0) / rect.height]
        else:
            effective_crop = None
        source = f"{asset['title']}，PDF 第 {asset['page']} 页" if asset.get("pdf_path") else asset.get("source", "")
        caption = str(item.get("caption", ""))
        resolved.append({**asset, "path": str(image_path.resolve()), "caption": caption,
                         "source": source, "requested_crop": crop, "crop": effective_crop})
    result["images"] = resolved
    result["layout"] = layout if resolved else "text"
    if resolved and layout == "text":
        result["layout"] = "image_right" if len(resolved) == 1 else "two_images"
    if len(resolved) == 2:
        result["layout"] = "two_images"
    return result


def draw_visual(spec: dict, output: Path) -> dict:
    """Draw bounded declarative charts; never execute model-generated code."""
    import math
    import textwrap
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
        if not isinstance(nodes, list) or not 2 <= len(nodes) <= 6 or not all(isinstance(n, str) and len(n) <= 60 for n in nodes):
            raise ValueError("流程图需要 2–6 个简短步骤")
    else:
        labels, values = spec.get("labels", []), spec.get("values", [])
        if (not isinstance(labels, list) or not isinstance(values, list) or
            not 2 <= len(labels) <= 12 or len(labels) != len(values) or
            not all(isinstance(n, str) and len(n) <= 50 for n in labels) or
            not all(type(v) in (int, float) and math.isfinite(v) for v in values)):
            raise ValueError("数据图需要 2–12 组有限数值和对应标签")
    output.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(json.dumps(spec, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:20]
    path = output / f"drawing-{digest}.png"
    with plt.rc_context({"font.sans-serif": ["Microsoft YaHei", "SimHei", "DejaVu Sans"], "axes.unicode_minus": False}):
        fig, ax = plt.subplots(figsize=(10, 5.5), constrained_layout=True)
        try:
            ax.set_title(str(spec.get("title", "")), fontsize=17, loc="left", pad=22)
            if kind == "flow":
                ax.set_xlim(0, 10)
                ax.set_ylim(0, 5)
                ax.axis("off")
                columns = len(nodes) if len(nodes) <= 3 else 3
                width = 9 / columns - .5
                locations = []
                for i, node in enumerate(nodes):
                    row, column = divmod(i, columns)
                    if row == 1:
                        column = columns - 1 - column
                    x = .5 + column * (9 / columns)
                    y = 1.7 if len(nodes) <= 3 else 3.0 - row * 2.3
                    locations.append((x, y))
                    ax.add_patch(FancyBboxPatch((x, y), width, 1.5, boxstyle="round,pad=0.05", facecolor="#e8f1fa", edgecolor="#245b8a"))
                    ax.text(x + width / 2, y + .75, textwrap.fill(node, 10), ha="center", va="center", fontsize=14)
                for (x, y), (nx, ny) in zip(locations, locations[1:]):
                    if ny != y:
                        start, end = (x + width / 2, y - .08), (nx + width / 2, ny + 1.58)
                    elif nx > x:
                        start, end = (x + width + .07, y + .75), (nx - .07, ny + .75)
                    else:
                        start, end = (x - .07, y + .75), (nx + width + .07, ny + .75)
                    ax.annotate("", xy=end, xytext=start, arrowprops={"arrowstyle": "->", "color": "#245b8a", "lw": 1.8})
            else:
                positions = list(range(len(labels)))
                if kind == "bar":
                    ax.bar(positions, values, color="#397aaa", width=.6)
                else:
                    ax.plot(positions, values, color="#397aaa", marker="o", linewidth=2)
                ax.set_xticks(positions, [textwrap.fill(label, 12) for label in labels], fontsize=10)
                ax.set_ylabel(str(spec.get("ylabel", "")))
                ax.spines[["top", "right"]].set_visible(False)
                ax.grid(axis="y", alpha=.18)
                for x, y in zip(positions, values):
                    ax.annotate(f"{y:g}", (x, y), xytext=(0, 7), textcoords="offset points", ha="center")
                ax.margins(y=.18)
            fig.savefig(path, dpi=190, facecolor="white")
            fig.savefig(path.with_suffix(".svg"), facecolor="white")
        finally:
            plt.close(fig)
    path.with_suffix(".json").write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"asset_id": digest, "path": str(path.resolve()), "kind": "drawn_chart", "title": spec.get("title", ""),
            "source": "根据原文整理绘制：" + source, "drawing_spec": spec}
