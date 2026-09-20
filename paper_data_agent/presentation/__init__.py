"""Presentation workspace, source-linked assets, and constrained drawings."""

from .assets import asset_prompt, collect_assets, collect_chart_assets, resolve_images
from .drawings import draw_visual
from .models import LAYOUTS, VISUAL_SCHEMA
from .workspace import load_spec, render_preview, replace_slide, revise_slide

__all__ = [
    "LAYOUTS",
    "VISUAL_SCHEMA",
    "asset_prompt",
    "collect_assets",
    "collect_chart_assets",
    "draw_visual",
    "load_spec",
    "render_preview",
    "replace_slide",
    "revise_slide",
    "resolve_images",
]
