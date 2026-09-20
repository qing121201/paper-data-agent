"""Extract, crop, validate, and preserve provenance for slide image assets."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re

from .drawings import draw_visual
from .models import LAYOUTS


def collect_assets(index, query: str, output: Path, limit: int = 8) -> list[dict]:
    import fitz

    words = set(re.findall(r"[a-z0-9]+", query.lower()))
    documents = {}
    for chunk in index.chunks:
        documents.setdefault(chunk.path, chunk.title)
    ranked = sorted(documents.items(), key=lambda row: -sum(
        len(word) for word in words if len(word) > 2 and word in row[1].lower()
    ))
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
                score = len(page.get_images()) * 2 + bool(page.get_drawings()) + len(captions)
                if re.search(r"(?im)^\s*(references|bibliography)\s*$", text):
                    score -= 30
                pages.append((score, number, captions))
            pages.sort(reverse=True)
            main = [entry for entry in pages if entry[1] < 8 and entry[0] > 0]
            selected = [main[0]] if main else []
            selected += [entry for entry in pages if entry not in selected][:2 - len(selected)]
            for _, number, captions in selected:
                page = pdf[number]
                digest = hashlib.sha256(
                    f"{path}:{Path(path).stat().st_mtime_ns}:{number}".encode()
                ).hexdigest()[:16]
                image = output / f"page-{digest}.png"
                if not image.exists():
                    page.get_pixmap(matrix=fitz.Matrix(1.8, 1.8), alpha=False).save(image)
                candidates.append({
                    "asset_id": digest,
                    "path": str(image.resolve()),
                    "pdf_path": path,
                    "title": title,
                    "page": number + 1,
                    "captions": captions[:6],
                    "text": page.get_text(),
                    "kind": "pdf_page",
                })
                if len(candidates) >= limit:
                    return candidates
    return candidates


def asset_prompt(assets: list[dict]) -> str:
    return "候选图片按下列顺序随请求发送：\n" + json.dumps(
        [
            {key: value for key, value in asset.items() if key not in {"path", "pdf_path"}}
            for asset in assets
        ],
        ensure_ascii=False,
    )


def collect_chart_assets(output_dir: Path, evidence: str) -> list[dict]:
    assets = []
    for path in output_dir.glob("*/figure.png"):
        if str(path) not in evidence and str(path.resolve()) not in evidence:
            continue
        manifest_path = path.parent / "manifest.json"
        if not manifest_path.is_file():
            continue
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assets.append({
            "asset_id": hashlib.sha256(str(path.resolve()).encode()).hexdigest()[:16],
            "path": str(path.resolve()),
            "kind": "data_chart",
            "title": path.parent.name,
            "source": "数据文件：" + str(manifest.get("source", "")),
            "captions": [str(manifest)],
        })
    return assets


def resolve_images(slide: dict, assets: list[dict], output: Path) -> dict:
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
        effective_crop = None
        if crop is not None:
            image_path, effective_crop = _crop_pdf_asset(asset, crop, output)
        source = (
            f"{asset['title']}，PDF 第 {asset['page']} 页"
            if asset.get("pdf_path") else asset.get("source", "")
        )
        resolved.append({
            **asset,
            "path": str(image_path.resolve()),
            "caption": str(item.get("caption", "")),
            "source": source,
            "requested_crop": crop,
            "crop": effective_crop,
        })
    result["images"] = resolved
    result["layout"] = layout if resolved else "text"
    if resolved and layout == "text":
        result["layout"] = "image_right" if len(resolved) == 1 else "two_images"
    if len(resolved) == 2:
        result["layout"] = "two_images"
    return result


def _crop_pdf_asset(asset: dict, crop: object, output: Path) -> tuple[Path, list[float]]:
    if (
        not isinstance(crop, list) or len(crop) != 4
        or not all(type(value) in (int, float) and 0 <= value <= 1 for value in crop)
        or crop[2] - crop[0] < .05 or crop[3] - crop[1] < .05
    ):
        raise ValueError("图片裁剪坐标无效")
    if asset.get("kind") != "pdf_page":
        raise ValueError("数据图暂不支持裁剪，请保留完整坐标轴")
    import fitz

    digest = hashlib.sha256(json.dumps([asset["asset_id"], crop]).encode()).hexdigest()[:20]
    output.mkdir(parents=True, exist_ok=True)
    image_path = output / f"crop-{digest}.png"
    with fitz.open(asset["pdf_path"]) as pdf:
        page = pdf[asset["page"] - 1]
        page_rect = page.rect
        clip = fitz.Rect(
            page_rect.x0 + page_rect.width * crop[0],
            page_rect.y0 + page_rect.height * crop[1],
            page_rect.x0 + page_rect.width * crop[2],
            page_rect.y0 + page_rect.height * crop[3],
        )
        substantial = []
        for info in page.get_image_info():
            box = fitz.Rect(info["bbox"])
            if box.width * box.height < page_rect.width * page_rect.height * .002:
                continue
            overlap = max(0, min(box.y1, clip.y1) - max(box.y0, clip.y0))
            if overlap >= min(box.height, clip.height) * .35:
                substantial.append(box)
        if substantial:
            visual = substantial[0]
            for box in substantial[1:]:
                visual |= box
            clip |= visual
        margin_x, margin_y = page_rect.width * .025, page_rect.height * .018
        clip = fitz.Rect(
            max(page_rect.x0, clip.x0 - margin_x),
            max(page_rect.y0, clip.y0 - margin_y),
            min(page_rect.x1, clip.x1 + margin_x),
            min(page_rect.y1, clip.y1 + margin_y),
        )
        page.get_pixmap(matrix=fitz.Matrix(2, 2), clip=clip, alpha=False).save(image_path)
    effective_crop = [
        (clip.x0 - page_rect.x0) / page_rect.width,
        (clip.y0 - page_rect.y0) / page_rect.height,
        (clip.x1 - page_rect.x0) / page_rect.width,
        (clip.y1 - page_rect.y0) / page_rect.height,
    ]
    return image_path, effective_crop
