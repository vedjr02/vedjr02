"""Generate an animated monochrome ASCII portrait SVG from the processed photo.

Algorithm notes:
- Sample luminance + Sobel edges (not brightness alone) so facial outlines
  survive aggressive downsampling into ~60 columns.
- Map high detail/brightness to denser glyphs so the portrait reads as green
  light on a dark terminal background.
- Emit one <text> node per line (not per character) to keep the SVG small.
- Use SMIL opacity reveals for a typewriter effect GitHub can render; no JS.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

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

# Density ramp for green-on-black terminals (sparse → dense).
# Avoid <>&"' so SVG text stays compact without entity noise.
ASCII_RAMP = " .:^~-_+?][}{1)(|/tfjrxnuvczXYUJCLQ0OZmwqpdbkhao*#MW8%B@$"
CHAR_ASPECT = 0.55  # typical monospace cell width / height


def load_luma_alpha(path: Path) -> tuple[np.ndarray, np.ndarray]:
    """Return float luma and alpha in [0, 1], shape (H, W)."""
    image = Image.open(path).convert("RGBA")
    arr = np.asarray(image, dtype=np.float32) / 255.0
    rgb = arr[:, :, :3]
    alpha = arr[:, :, 3]
    # Rec. 709 luma
    luma = 0.2126 * rgb[:, :, 0] + 0.7152 * rgb[:, :, 1] + 0.0722 * rgb[:, :, 2]
    return luma, alpha


def edge_magnitude(luma: np.ndarray) -> np.ndarray:
    """Sobel edge strength normalized to [0, 1]."""
    u8 = np.clip(luma * 255.0, 0, 255).astype(np.uint8)
    gx = cv2.Sobel(u8, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(u8, cv2.CV_32F, 0, 1, ksize=3)
    mag = cv2.magnitude(gx, gy)
    peak = float(mag.max()) or 1.0
    return mag / peak


def stretch_opaque(score: np.ndarray, alpha: np.ndarray, threshold: float) -> np.ndarray:
    """Percentile-stretch opaque pixels so a dark hoodie still uses the full ramp."""
    mask = alpha >= threshold
    if not np.any(mask):
        return score
    lo, hi = np.percentile(score[mask], (5, 98))
    if hi <= lo:
        return score
    stretched = (score - lo) / (hi - lo)
    return np.clip(stretched, 0.0, 1.0)


def image_to_ascii(
    luma: np.ndarray,
    alpha: np.ndarray,
    columns: int,
    *,
    edge_weight: float = 0.40,
    alpha_threshold: float = 0.12,
) -> list[str]:
    """Downsample the portrait into ASCII lines."""
    height, width = luma.shape
    rows = max(1, int(round(columns * (height / width) * CHAR_ASPECT)))

    # Mild gamma lift before blending — recovers shadowed face detail.
    lifted = np.power(np.clip(luma, 0.0, 1.0), 0.75)
    score = (1.0 - edge_weight) * lifted + edge_weight * edge_magnitude(luma)
    score = stretch_opaque(score, alpha, alpha_threshold)
    # Transparent pixels should become spaces.
    score = np.where(alpha >= alpha_threshold, score, 0.0)

    resized_score = cv2.resize(score, (columns, rows), interpolation=cv2.INTER_AREA)
    resized_alpha = cv2.resize(alpha, (columns, rows), interpolation=cv2.INTER_AREA)

    ramp = ASCII_RAMP
    last = len(ramp) - 1
    lines: list[str] = []
    for y in range(rows):
        chars: list[str] = []
        for x in range(columns):
            if resized_alpha[y, x] < alpha_threshold:
                chars.append(" ")
                continue
            idx = int(resized_score[y, x] * last + 1e-6)
            chars.append(ramp[min(max(idx, 0), last)])
        lines.append("".join(chars).rstrip())
    # Drop fully empty trailing lines from crop padding.
    while lines and not lines[-1].strip():
        lines.pop()
    while lines and not lines[0].strip():
        lines.pop(0)
    return lines


def terminal_frame(
    inner_width: float,
    inner_height: float,
    *,
    title: str,
    colors: dict[str, str],
    padding: float = 16.0,
    title_bar: float = 28.0,
) -> tuple[str, float, float, float, float]:
    """Return (markup, content_x, content_y, total_w, total_h)."""
    total_w = inner_width + padding * 2
    total_h = inner_height + padding * 2 + title_bar
    bg = xml_escape(colors["background"])
    dim = xml_escape(colors["dim"])
    muted = xml_escape(colors["muted"])
    fg = xml_escape(colors["foreground"])
    accent = xml_escape(colors["accent"])

    markup = f"""
  <rect x="0.5" y="0.5" width="{total_w - 1}" height="{total_h - 1}" rx="8" ry="8"
        fill="{bg}" stroke="{dim}" stroke-width="1"/>
  <rect x="0.5" y="0.5" width="{total_w - 1}" height="{title_bar}" rx="8" ry="8"
        fill="{dim}" stroke="none"/>
  <rect x="0.5" y="{title_bar - 8}" width="{total_w - 1}" height="8" fill="{dim}"/>
  <circle cx="18" cy="{title_bar / 2}" r="4" fill="{muted}"/>
  <circle cx="34" cy="{title_bar / 2}" r="4" fill="{muted}"/>
  <circle cx="50" cy="{title_bar / 2}" r="4" fill="{muted}"/>
  <text x="{total_w / 2}" y="{title_bar / 2 + 4}" text-anchor="middle"
        font-family="ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace"
        font-size="11" fill="{accent}">{xml_escape(title)}</text>
"""
    return markup, padding, title_bar + padding * 0.5, total_w, total_h


def build_ascii_svg(
    lines: list[str],
    colors: dict[str, str],
    *,
    duration_s: float,
    show_cursor: bool,
    frame_window: bool,
    window_title: str,
    font_size: float = 8.0,
    line_height: float | None = None,
) -> str:
    """Compose the animated ASCII SVG document."""
    if not lines:
        raise ValueError("No ASCII lines generated from photo")

    line_height = line_height or font_size * 1.15
    max_cols = max(len(line) for line in lines)
    char_width = font_size * 0.62
    inner_w = max_cols * char_width
    inner_h = len(lines) * line_height + font_size

    offset_x = 0.0
    offset_y = font_size
    frame_markup = ""
    total_w, total_h = round(inner_w + 8, 2), round(inner_h + 8, 2)

    if frame_window:
        frame_markup, ox, oy, total_w, total_h = terminal_frame(
            inner_w,
            inner_h,
            title=window_title,
            colors=colors,
        )
        offset_x, offset_y = ox, oy + font_size
        total_w, total_h = round(total_w, 2), round(total_h, 2)

    fg = xml_escape(colors["foreground"])
    accent = xml_escape(colors["accent"])
    n = len(lines)
    # Stagger line reveals across the configured duration.
    step = duration_s / max(n, 1)

    text_nodes: list[str] = []
    for i, line in enumerate(lines):
        y = offset_y + i * line_height
        begin = f"{i * step:.3f}s"
        safe = xml_escape(line) if line else " "
        text_nodes.append(
            f'  <text x="{offset_x:.2f}" y="{y:.2f}" xml:space="preserve" opacity="0" '
            f'font-family="ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace" '
            f'font-size="{font_size}" fill="{fg}">'
            f"{safe}"
            f'<animate attributeName="opacity" from="0" to="1" begin="{begin}" '
            f'dur="0.05s" fill="freeze"/>'
            f"</text>"
        )

    cursor_markup = ""
    if show_cursor:
        # Block cursor rides down the left gutter, then freezes (plays once).
        cursor_x = offset_x + max_cols * char_width + 2
        ys = [offset_y + i * line_height - font_size * 0.75 for i in range(n)]
        values = ";".join(f"{y:.2f}" for y in ys)
        key_times = ";".join(f"{i / max(n - 1, 1):.4f}" for i in range(n))
        cursor_markup = f"""
  <rect x="{cursor_x:.2f}" y="{ys[0]:.2f}" width="{char_width:.2f}" height="{font_size:.2f}"
        fill="{accent}" opacity="1">
    <animate attributeName="y" values="{values}" keyTimes="{key_times}"
             dur="{duration_s:.3f}s" calcMode="discrete" fill="freeze"/>
    <animate attributeName="opacity" values="1;0;1;0;1;0;1"
             keyTimes="0;0.16;0.33;0.5;0.66;0.83;1"
             begin="{duration_s:.3f}s" dur="1.2s" fill="freeze"/>
  </rect>
"""

    body = frame_markup + "\n".join(text_nodes) + cursor_markup
    background = None if frame_window else colors["background"]
    return svg_document(total_w, total_h, body, background=background)


def generate(config: dict | None = None) -> Path:
    """Generate avi-ascii.svg from the processed photo and profile config."""
    config = config or load_config()
    colors = theme_colors(config)
    photo = resolve_path(config["paths"]["photo_processed"])
    output = resolve_path(config["paths"]["ascii_svg"])
    columns = int(config.get("layout", {}).get("ascii_columns", 60))
    duration = float(config.get("animation", {}).get("ascii_duration_s", 2.5))
    show_cursor = bool(config.get("animation", {}).get("ascii_cursor", True))
    frame_window = bool(config.get("layout", {}).get("frame_window", True))
    title = str(config.get("theme", {}).get("window_title", "ascii"))

    if not photo.is_file():
        raise FileNotFoundError(
            f"Processed photo missing: {photo}. Run scripts/prep_photo.py first."
        )

    log.info("Loading %s", photo)
    luma, alpha = load_luma_alpha(photo)
    lines = image_to_ascii(luma, alpha, columns)
    log.info("ASCII grid: %s lines × ~%s cols", len(lines), columns)

    svg = build_ascii_svg(
        lines,
        colors,
        duration_s=duration,
        show_cursor=show_cursor,
        frame_window=frame_window,
        window_title=title,
    )
    write_text(output, svg)
    log.info("Wrote %s (%s bytes)", output, output.stat().st_size)
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate animated ASCII portrait SVG")
    parser.add_argument("--columns", type=int, default=None)
    args = parser.parse_args()

    config = load_config()
    if args.columns is not None:
        config.setdefault("layout", {})["ascii_columns"] = args.columns
    generate(config)


if __name__ == "__main__":
    main()
