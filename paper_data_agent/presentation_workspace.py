"""Compatibility facade for versioned presentation workspaces."""

from .presentation.workspace import load_spec, render_preview, replace_slide, revise_slide

__all__ = ["load_spec", "render_preview", "replace_slide", "revise_slide"]
