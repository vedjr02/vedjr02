"""Generate a Neofetch-inspired animated terminal info-card SVG.

Reads identity + info_card fields from config/profile.yaml and emits
assets/info-card.svg. Rows reveal one-by-one via SMIL (GitHub-safe, no JS).
"""

from __future__ import annotations

import argparse
import textwrap
from dataclasses import dataclass
from typing import Any

from common import (
    load_config,
    resolve_path,
    setup_logging,
    svg_document,
    theme_colors,
    write_text,
    xml_escape,
)

log = setup_logging()

FONT = "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace"


@dataclass(frozen=True)
class Row:
    """One terminal line in the info card."""

    label: str
    value: str
    kind: str = "kv"  # kv | header | rule | blank | prompt


def build_rows(config: dict[str, Any]) -> list[Row]:
    """Assemble neofetch-style rows from profile config."""
    identity = config.get("identity", {})
    card = config.get("info_card", {})
    username = str(config.get("github_username", "user"))
    name = str(identity.get("display_name", username))
    prompt = str(identity.get("prompt", f"{username}@github:~$"))

    def join(items: Any, sep: str = ", ") -> str:
        if not items:
            return "—"
        if isinstance(items, str):
            return items
        return sep.join(str(x) for x in items)

    rows: list[Row] = [
        Row("", f"{prompt} neofetch", kind="prompt"),
        Row("", "", kind="blank"),
        Row("", f"{name}@{username}", kind="header"),
        Row("", "---------------------------", kind="rule"),
        Row("Role", str(identity.get("role", "—"))),
        Row("Location", str(identity.get("location", "—"))),
        Row("Education", str(identity.get("education", "—"))),
        Row("Languages", join(card.get("languages"))),
        Row("Tech", join(card.get("tech_stack"))),
        Row("Interests", join(card.get("interests"))),
        Row("Focus", str(card.get("current_focus", "—"))),
        Row("Fun", join(card.get("fun_facts"), " · ")),
        Row("Web", str(identity.get("website", "—"))),
        Row("", "", kind="blank"),
        Row("", f"{prompt} ", kind="prompt"),
    ]
    return rows


def wrap_value(label: str, value: str, width: int) -> list[tuple[str, str]]:
    """Word-wrap long values; continuation lines indent under the value column."""
    label_width = 12
    available = max(16, width - label_width - 2)
    if not value:
        return [(label, "")]
    parts = textwrap.wrap(value, width=available) or [value]
    out: list[tuple[str, str]] = [(label, parts[0])]
    for part in parts[1:]:
        out.append(("", part))
    return out


def expand_rows(rows: list[Row], width: int) -> list[Row]:
    """Apply wrapping to key/value rows."""
    expanded: list[Row] = []
    for row in rows:
        if row.kind != "kv":
            expanded.append(row)
            continue
        for label, value in wrap_value(row.label, row.value, width):
            expanded.append(Row(label, value, kind="kv"))
    return expanded


def terminal_chrome(
    total_w: float,
    total_h: float,
    *,
    title: str,
    colors: dict[str, str],
    title_bar: float = 28.0,
) -> str:
    """Framed window matching the ASCII portrait chrome."""
    bg = xml_escape(colors["background"])
    dim = xml_escape(colors["dim"])
    muted = xml_escape(colors["muted"])
    accent = xml_escape(colors["accent"])
    return f"""
  <rect x="0.5" y="0.5" width="{total_w - 1}" height="{total_h - 1}" rx="8" ry="8"
        fill="{bg}" stroke="{dim}" stroke-width="1"/>
  <rect x="0.5" y="0.5" width="{total_w - 1}" height="{title_bar}" rx="8" ry="8"
        fill="{dim}" stroke="none"/>
  <rect x="0.5" y="{title_bar - 8}" width="{total_w - 1}" height="8" fill="{dim}"/>
  <circle cx="18" cy="{title_bar / 2}" r="4" fill="{muted}"/>
  <circle cx="34" cy="{title_bar / 2}" r="4" fill="{muted}"/>
  <circle cx="50" cy="{title_bar / 2}" r="4" fill="{muted}"/>
  <text x="{total_w / 2}" y="{title_bar / 2 + 4}" text-anchor="middle"
        font-family="{FONT}" font-size="11" fill="{accent}">{xml_escape(title)}</text>
"""


def render_line_svg(
    row: Row,
    *,
    x: float,
    y: float,
    colors: dict[str, str],
    font_size: float,
    begin: str,
) -> str:
    """One animated line. Labels use accent; values use foreground."""
    fg = xml_escape(colors["foreground"])
    accent = xml_escape(colors["accent"])
    muted = xml_escape(colors["muted"])
    anim = (
        f'<animate attributeName="opacity" from="0" to="1" begin="{begin}" '
        f'dur="0.08s" fill="freeze"/>'
    )

    if row.kind == "blank":
        return ""

    if row.kind in {"prompt", "header", "rule"}:
        color = accent if row.kind != "rule" else muted
        return (
            f'  <text x="{x:.2f}" y="{y:.2f}" opacity="0" font-family="{FONT}" '
            f'font-size="{font_size}" fill="{color}">{xml_escape(row.value)}{anim}</text>'
        )

    # key/value — neofetch style: "Label: value"
    label_gap = 12 * (font_size * 0.62)
    label_node = ""
    if row.label:
        label = f"{row.label}:"
        label_node = (
            f'  <text x="{x:.2f}" y="{y:.2f}" opacity="0" font-family="{FONT}" '
            f'font-size="{font_size}" fill="{accent}">{xml_escape(label)}{anim}</text>\n'
        )
    value_x = x + label_gap
    value_node = (
        f'  <text x="{value_x:.2f}" y="{y:.2f}" opacity="0" font-family="{FONT}" '
        f'font-size="{font_size}" fill="{fg}">{xml_escape(row.value)}{anim}</text>'
    )
    return label_node + value_node


def build_info_card_svg(config: dict[str, Any]) -> str:
    """Compose the full info-card SVG document."""
    colors = theme_colors(config)
    animation = config.get("animation", {})
    duration = float(animation.get("ascii_duration_s", 2.5))
    # Slightly longer than ASCII so the card finishes after the portrait.
    duration = max(duration, 2.8)
    frame = bool(config.get("layout", {}).get("frame_window", True))
    title = str(config.get("theme", {}).get("window_title", "neofetch"))

    font_size = 13.0
    line_height = font_size * 1.45
    content_width_chars = 56
    padding = 18.0
    title_bar = 28.0 if frame else 0.0

    rows = expand_rows(build_rows(config), content_width_chars)
    visible = [r for r in rows if r.kind != "blank"]
    # Keep blanks for vertical rhythm but they don't consume animation slots.
    char_w = font_size * 0.62
    inner_w = content_width_chars * char_w
    inner_h = len(rows) * line_height + font_size

    total_w = round(inner_w + padding * 2, 2)
    total_h = round(inner_h + padding * 2 + title_bar, 2)
    origin_x = padding
    origin_y = title_bar + padding + font_size

    chrome = (
        terminal_chrome(total_w, total_h, title=title, colors=colors, title_bar=title_bar)
        if frame
        else ""
    )

    step = duration / max(len(visible), 1)
    parts: list[str] = [chrome]
    vis_index = 0
    for i, row in enumerate(rows):
        y = origin_y + i * line_height
        if row.kind == "blank":
            continue
        begin = f"{vis_index * step:.3f}s"
        parts.append(
            render_line_svg(
                row,
                x=origin_x,
                y=y,
                colors=colors,
                font_size=font_size,
                begin=begin,
            )
        )
        vis_index += 1

    # Blinking block cursor at the final prompt (plays a few times, then freezes on).
    last_prompt_y = origin_y + (len(rows) - 1) * line_height
    prompt_text = next(
        (r.value for r in reversed(rows) if r.kind == "prompt"),
        "",
    )
    cursor_x = origin_x + len(prompt_text) * char_w
    accent = xml_escape(colors["accent"])
    parts.append(
        f'  <rect x="{cursor_x:.2f}" y="{last_prompt_y - font_size + 2:.2f}" '
        f'width="{char_w:.2f}" height="{font_size:.2f}" fill="{accent}" opacity="0">'
        f'<animate attributeName="opacity" values="0;1;0;1;0;1;1" '
        f'keyTimes="0;0.15;0.3;0.45;0.6;0.75;1" '
        f'begin="{duration:.3f}s" dur="1.4s" fill="freeze"/>'
        f"</rect>"
    )

    background = None if frame else colors["background"]
    return svg_document(total_w, total_h, "\n".join(parts), background=background)


def generate(config: dict[str, Any] | None = None):
    """Write info-card.svg and return its path."""
    config = config or load_config()
    output = resolve_path(config["paths"]["info_card_svg"])
    svg = build_info_card_svg(config)
    write_text(output, svg)
    log.info("Wrote %s (%s bytes)", output, output.stat().st_size)
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate neofetch info-card SVG")
    parser.parse_args()
    generate()


if __name__ == "__main__":
    main()
