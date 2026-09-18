"""Versioned editing of the app's generated slide specifications."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import subprocess
from typing import Any

from .adapters import PROJECT_ROOT, WINDOWS_NO_WINDOW, ResearchToolAdapters
from .workflow import ResearchWorkflowAgent


def load_spec(path: Path) -> dict[str, Any]:
    spec = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(spec, dict) or not isinstance(spec.get("slides"), list):
        raise ValueError("这不是 Agent 生成的演示文稿项目")
    return spec


def replace_slide(spec: dict[str, Any], page: int, replacement: dict[str, Any]) -> dict[str, Any]:
    """Page 0 is the cover; other pages index the content slide array."""
    if not isinstance(replacement, dict) or not 0 <= page <= len(spec["slides"]):
        raise ValueError("页码或修改内容无效")
    updated = deepcopy(spec)
    if page == 0:
        for key in ("title", "subtitle"):
            if key in replacement:
                if not isinstance(replacement[key], str):
                    raise ValueError(f"{key} 必须是文字")
                updated[key] = replacement[key]
    else:
        target = updated["slides"][page - 1]
        for key in ("title", "bullets", "source", "images", "layout"):
            if key not in replacement:
                continue
            value = replacement[key]
            if key == "bullets":
                if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
                    raise ValueError("正文必须是文字列表")
                if len(value) > 7 or any(len(item) > 320 for item in value):
                    raise ValueError("这一页内容过长，请要求模型缩短")
            elif key == "images":
                if not isinstance(value, list) or len(value) > 2:
                    raise ValueError("每页最多两张图片")
            elif key == "layout":
                from .paper_visuals import LAYOUTS
                if value not in LAYOUTS:
                    raise ValueError("未知图文布局")
            elif not isinstance(value, str):
                raise ValueError(f"{key} 必须是文字")
            target[key] = value
    return updated


def render_preview(spec_path: Path) -> list[Path]:
    deck = spec_path.parent / "paper-presentation.pptx"
    if not deck.is_file():
        raise ValueError("未找到此版本的 PPTX")
    output = spec_path.parent / "preview"
    images = list(output.glob("*.PNG")) + list(output.glob("*.png")) if output.exists() else []
    expected = len(load_spec(spec_path)["slides"]) + 1
    if len(set(images)) != expected:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
             str(PROJECT_ROOT / "scripts" / "render_presentation.ps1"),
             "-PptxPath", str(deck.resolve()), "-OutputDir", str(output.resolve())],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180,
            creationflags=WINDOWS_NO_WINDOW,
        )
        if result.returncode:
            raise RuntimeError("PPT 文件已保留，但 PowerPoint 预览导出失败：" + (result.stderr or result.stdout)[-500:])
    import re
    images = set(output.glob("*.PNG")) | set(output.glob("*.png"))
    ordered = sorted(images, key=lambda item: int(re.search(r"(\d+)$", item.stem).group(1)))
    if len(ordered) != expected:
        raise RuntimeError("预览页数不完整，请重新生成预览")
    return ordered


def revise_slide(spec_path: Path, page: int, instruction: str, client) -> Path:
    original = load_spec(spec_path)
    current = ({"title": original.get("title", ""), "subtitle": original.get("subtitle", "")}
               if page == 0 else original["slides"][page - 1])
    from .paper_visuals import collect_assets, asset_prompt, resolve_images, VISUAL_SCHEMA
    from .core import PaperIndex
    assets = [{**asset, "kind": "saved_image"} for asset in current.get("images", [])]
    asset_dir = spec_path.parent.parent / "visual_assets"
    wants_images = any(word in instruction.lower() for word in ("图", "image", "figure", "picture"))
    index_path = spec_path.parent.parent.parent / "index.json"
    if page and wants_images and index_path.is_file():
        assets += collect_assets(PaperIndex.load(index_path), str(current.get("title", "")) + " " + instruction, asset_dir, limit=6)
    assets = list({a["asset_id"]: a for a in assets}.values())
    allowed = "title, subtitle" if page == 0 else "title, bullets（字符串列表）, source, layout, images, drawing"
    raw = client.generate(
        f"你是论文汇报逐页编辑器。只修改用户选中的这一页，只返回 JSON 对象，字段为 {allowed}。"
        "不要虚构数据、论文或来源。保留已有来源。上下页只是参考，不要修改。"
        + ("封面暂只支持标题和副标题。" if page == 0 else VISUAL_SCHEMA)
        + "未要求修改图片时省略 images，保留原图；要求加图时必须选择相关候选图片，没有合适图片返回 error 说明原因。"
        "使用自然中文。正文最多 7 条，每条最多 320 字。",
        "当前页：\n" + json.dumps(current, ensure_ascii=False)
        + "\n整份文稿上下文（参考数据）：\n" + json.dumps(original, ensure_ascii=False)
        + f"\n用户对第 {page + 1} 页的修改要求：\n{instruction}\n" + asset_prompt(assets),
        image_paths=[a["path"] for a in assets],
        reasoning_effort="high",
        max_output_tokens=getattr(getattr(client, "config", None), "max_output_tokens", None),
    )
    replacement = ResearchWorkflowAgent._parse_json_object(raw)
    # Keep the proposal for troubleshooting without losing a costly model response.
    from datetime import datetime
    proposal_dir = spec_path.parent.parent / "edit_proposals"
    proposal_dir.mkdir(exist_ok=True)
    proposal = {"parent": str(spec_path), "page": page, "instruction": instruction, "replacement": replacement}
    (proposal_dir / (datetime.now().strftime("%Y%m%d-%H%M%S-%f") + ".json")).write_text(
        json.dumps(proposal, ensure_ascii=False, indent=2), encoding="utf-8")
    if replacement.get("error"):
        raise ValueError(str(replacement["error"]))
    if "images" in replacement or "drawing" in replacement:
        replacement = resolve_images(replacement, assets, asset_dir)
    if page and any(word in instruction for word in ("加图", "加入", "插入", "换图", "换成")) and wants_images and not replacement.get("images"):
        raise ValueError("模型未选出可插入的图片，旧版未改动。请指定论文名称或 Figure 编号重试。")
    updated = replace_slide(original, page, replacement)
    if updated == original:
        raise ValueError("模型没有返回有效修改，旧版保持不变")
    result = ResearchToolAdapters(spec_path.parent.parent).create_presentation(updated)
    new_spec = next(Path(path) for path in result.files if Path(path).name == "presentation_spec.json")
    revision = {"parent": str(spec_path), "page": page + 1, "instruction": instruction}
    (new_spec.parent / "revision.json").write_text(json.dumps(revision, ensure_ascii=False, indent=2), encoding="utf-8")
    return new_spec
