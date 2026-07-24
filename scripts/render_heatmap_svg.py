"""Render an animated contribution heatmap SVG from contributions.json.

Visual language matches the terminal theme (green-on-black). Cells reveal
on a diagonal wave via SMIL so the animation works on GitHub without JS.
"""

from __future__ import annotations

import argparse
import json
from calendar import month_abbr
from datetime import date, timedelta
from pathlib import Path
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

# Intensity ramp tuned for classic-green terminal look (level 0–4).
LEVEL_COLORS = (
    "#0d1117",  # empty — near background
    "#1a3d24",  # low
    "#238636",
    "#3fb950",
    "#33ff66",  # peak — matches foreground
)


def load_contributions(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(
            f"Missing {path}. Run scripts/fetch_contributions.py first."
        )
    return json.loads(path.read_text(encoding="utf-8"))


def group_into_weeks(days: list[dict[str, Any]]) -> list[list[dict[str, Any] | None]]:
    """Bucket days into Sunday-start weeks (GitHub calendar convention)."""
    if not days:
        return []

    parsed = [(date.fromisoformat(d["date"]), d) for d in days]
    parsed.sort(key=lambda item: item[0])

    start = parsed[0][0]
    # Pad back to Sunday (weekday(): Mon=0 … Sun=6 → Sunday offset)
    start_pad = (start.weekday() + 1) % 7
    cursor = start - timedelta(days=start_pad)

    by_date = {d.isoformat(): payload for d, payload in parsed}
    end = parsed[-1][0]

    weeks: list[list[dict[str, Any] | None]] = []
    while cursor <= end:
        week: list[dict[str, Any] | None] = []
        for _ in range(7):
            week.append(by_date.get(cursor.isoformat()))
            cursor += timedelta(days=1)
        weeks.append(week)
    return weeks


def month_labels(weeks: list[list[dict[str, Any] | None]]) -> list[tuple[int, str]]:
    """Return (week_index, month_abbr) when the month changes."""
    labels: list[tuple[int, str]] = []
    last_month: int | None = None
    for index, week in enumerate(weeks):
        # Prefer mid-week day for stable month tagging.
        sample = next((d for d in week if d), None)
        if not sample:
            continue
        month = date.fromisoformat(sample["date"]).month
        if month != last_month:
            labels.append((index, month_abbr[month]))
            last_month = month
    return labels


def terminal_chrome(
    total_w: float,
    total_h: float,
    *,
    title: str,
    colors: dict[str, str],
    title_bar: float = 28.0,
) -> str:
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


def format_stats_line(stats: dict[str, Any]) -> str:
    best = stats.get("best_day") or "—"
    best_count = stats.get("best_day_count", 0)
    return (
        f"Total: {stats.get('total', 0):,}   "
        f"Current streak: {stats.get('current_streak', 0)}   "
        f"Longest streak: {stats.get('longest_streak', 0)}   "
        f"Best day: {best_count:,} on {best}"
    )


def build_heatmap_svg(config: dict[str, Any], data: dict[str, Any]) -> str:
    colors = theme_colors(config)
    duration = float(config.get("animation", {}).get("heatmap_duration_s", 3.0))
    frame = bool(config.get("layout", {}).get("frame_window", True))
    title = str(config.get("theme", {}).get("window_title", "contributions"))

    weeks = group_into_weeks(list(data.get("days", [])))
    if not weeks:
        raise ValueError("No contribution days to render")

    # Geometry
    cell = 11.0
    gap = 3.0
    step = cell + gap
    label_w = 28.0
    padding = 18.0
    title_bar = 28.0 if frame else 0.0
    stats_h = 22.0
    month_h = 18.0
    legend_h = 24.0

    grid_w = len(weeks) * step - gap
    grid_h = 7 * step - gap
    inner_w = label_w + grid_w
    inner_h = stats_h + month_h + grid_h + legend_h + 8

    total_w = round(inner_w + padding * 2, 2)
    total_h = round(inner_h + padding * 2 + title_bar, 2)

    origin_x = padding
    origin_y = title_bar + padding
    grid_x = origin_x + label_w
    grid_y = origin_y + stats_h + month_h

    fg = xml_escape(colors["foreground"])
    accent = xml_escape(colors["accent"])
    muted = xml_escape(colors["muted"])
    dim = xml_escape(colors["dim"])

    parts: list[str] = []
    if frame:
        parts.append(
            terminal_chrome(total_w, total_h, title=title, colors=colors, title_bar=title_bar)
        )

    # Stats header
    stats_text = format_stats_line(data.get("stats", {}))
    parts.append(
        f'  <text x="{origin_x:.2f}" y="{origin_y + 14:.2f}" font-family="{FONT}" '
        f'font-size="12" fill="{fg}" opacity="0">{xml_escape(stats_text)}'
        f'<animate attributeName="opacity" from="0" to="1" begin="0s" dur="0.2s" fill="freeze"/>'
        f"</text>"
    )

    # Month labels
    for week_index, label in month_labels(weeks):
        x = grid_x + week_index * step
        parts.append(
            f'  <text x="{x:.2f}" y="{origin_y + stats_h + 12:.2f}" font-family="{FONT}" '
            f'font-size="10" fill="{muted}">{xml_escape(label)}</text>'
        )

    # Weekday labels (Sun-start grid: show Mon/Wed/Fri)
    weekday_labels = {1: "Mon", 3: "Wed", 5: "Fri"}
    for dow, label in weekday_labels.items():
        y = grid_y + dow * step + cell - 2
        parts.append(
            f'  <text x="{origin_x:.2f}" y="{y:.2f}" font-family="{FONT}" '
            f'font-size="9" fill="{muted}">{label}</text>'
        )

    # Diagonal wave: delay ~ (week + dow)
    max_diag = (len(weeks) - 1) + 6
    diag_step = duration / max(max_diag, 1)

    for week_index, week in enumerate(weeks):
        for dow, day in enumerate(week):
            if day is None:
                continue
            level = int(day.get("level", 0))
            level = max(0, min(level, 4))
            fill = LEVEL_COLORS[level]
            x = grid_x + week_index * step
            y = grid_y + dow * step
            begin = f"{(week_index + dow) * diag_step:.3f}s"
            count = int(day.get("count", 0))
            day_id = day.get("date", "")
            title_attr = xml_escape(f"{count} contribution{'s' if count != 1 else ''} on {day_id}")
            stroke = dim if level == 0 else fill
            parts.append(
                f'  <rect x="{x:.2f}" y="{y:.2f}" width="{cell}" height="{cell}" rx="2" ry="2" '
                f'fill="{fill}" stroke="{stroke}" stroke-width="0.5" opacity="0">'
                f"<title>{title_attr}</title>"
                f'<animate attributeName="opacity" from="0" to="1" begin="{begin}" '
                f'dur="0.12s" fill="freeze"/>'
                f"</rect>"
            )

    # Legend
    legend_y = grid_y + grid_h + 16
    parts.append(
        f'  <text x="{origin_x:.2f}" y="{legend_y:.2f}" font-family="{FONT}" '
        f'font-size="10" fill="{muted}">Less</text>'
    )
    legend_x = origin_x + 36
    for level, color in enumerate(LEVEL_COLORS):
        x = legend_x + level * step
        parts.append(
            f'  <rect x="{x:.2f}" y="{legend_y - cell + 2:.2f}" width="{cell}" height="{cell}" '
            f'rx="2" ry="2" fill="{color}" stroke="{dim}" stroke-width="0.5"/>'
        )
    parts.append(
        f'  <text x="{legend_x + 5 * step:.2f}" y="{legend_y:.2f}" font-family="{FONT}" '
        f'font-size="10" fill="{muted}">More</text>'
    )

    # Footer: date range is stable when contribution data is unchanged
    # (avoids empty CI commits from a wall-clock timestamp).
    first_sample = next((d for d in weeks[0] if d), None)
    last_sample = next((d for d in reversed(weeks[-1]) if d), first_sample)
    if first_sample and last_sample:
        parts.append(
            f'  <text x="{total_w - padding:.2f}" y="{legend_y:.2f}" text-anchor="end" '
            f'font-family="{FONT}" font-size="9" fill="{accent}">'
            f'{xml_escape(first_sample["date"])} → {xml_escape(last_sample["date"])}</text>'
        )

    background = None if frame else colors["background"]
    return svg_document(total_w, total_h, "\n".join(parts), background=background)


def generate(config: dict[str, Any] | None = None) -> Path:
    config = config or load_config()
    data_path = resolve_path(config["paths"]["contributions_json"])
    output = resolve_path(config["paths"]["heatmap_svg"])
    data = load_contributions(data_path)
    svg = build_heatmap_svg(config, data)
    write_text(output, svg)
    log.info("Wrote %s (%s bytes)", output, output.stat().st_size)
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="Render contribution heatmap SVG")
    parser.parse_args()
    generate()


if __name__ == "__main__":
    main()
