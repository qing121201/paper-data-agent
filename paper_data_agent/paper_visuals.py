"""Compatibility facade for presentation visual assets and drawings."""

from .presentation import (
    LAYOUTS,
    VISUAL_SCHEMA,
    asset_prompt,
    collect_assets,
    collect_chart_assets,
    draw_visual,
    resolve_images,
)

__all__ = [
    "LAYOUTS",
    "VISUAL_SCHEMA",
    "asset_prompt",
    "collect_assets",
    "collect_chart_assets",
    "draw_visual",
    "resolve_images",
]
