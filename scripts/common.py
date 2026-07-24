"""Shared helpers for the profile-art generation pipeline.

Centralizes paths, theme loading, logging, and small SVG utilities so
individual generators stay focused and consistent.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any

import yaml

# Repository root (parent of scripts/)
REPO_ROOT: Path = Path(__file__).resolve().parent.parent
CONFIG_PATH: Path = REPO_ROOT / "config" / "profile.yaml"


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    """Configure root logging once and return a module-friendly logger."""
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)-7s | %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stdout,
        force=True,
    )
    return logging.getLogger("profile-art")


def load_config(path: Path | None = None) -> dict[str, Any]:
    """Load profile.yaml. Raises FileNotFoundError / ValueError on bad input."""
    config_path = path or CONFIG_PATH
    if not config_path.is_file():
        raise FileNotFoundError(f"Missing config: {config_path}")

    with config_path.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle)

    if not isinstance(data, dict):
        raise ValueError(f"Config must be a mapping: {config_path}")

    return data


def resolve_path(relative: str | Path) -> Path:
    """Resolve a path from profile.yaml relative to the repo root."""
    path = Path(relative)
    if path.is_absolute():
        return path
    return REPO_ROOT / path


def ensure_parent(path: Path) -> None:
    """Create parent directories for an output file if needed."""
    path.parent.mkdir(parents=True, exist_ok=True)


def xml_escape(text: str) -> str:
    """Escape text for safe inclusion in SVG/XML content."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def theme_colors(config: dict[str, Any]) -> dict[str, str]:
    """Return the theme color map with required keys validated."""
    theme = config.get("theme")
    if not isinstance(theme, dict):
        raise ValueError("config.theme must be a mapping")

    required = ("background", "foreground", "dim", "muted", "accent")
    missing = [key for key in required if key not in theme]
    if missing:
        raise ValueError(f"config.theme missing keys: {', '.join(missing)}")

    return {key: str(theme[key]) for key in (*required, "window_title", "name") if key in theme}


def svg_document(
    width: int | float,
    height: int | float,
    body: str,
    *,
    background: str | None = None,
) -> str:
    """Wrap inner SVG markup in a complete document string."""
    bg_rect = ""
    if background:
        bg_rect = (
            f'<rect width="100%" height="100%" fill="{xml_escape(background)}"/>\n  '
        )

    return (
        f'<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img">\n'
        f"  {bg_rect}{body.strip()}\n"
        f"</svg>\n"
    )


def write_text(path: Path, content: str) -> None:
    """Write UTF-8 text, creating parent dirs as needed."""
    ensure_parent(path)
    path.write_text(content, encoding="utf-8")
