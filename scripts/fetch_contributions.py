"""Fetch public GitHub contribution data without a personal access token.

Scrapes https://github.com/users/<username>/contributions and writes
data/contributions.json for the heatmap renderer.

GitHub's calendar HTML can change; parsing is defensive and fails loudly.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import requests
from bs4 import BeautifulSoup

from common import load_config, resolve_path, setup_logging, write_text

log = setup_logging()

USER_AGENT = "vedjr02-profile-art/1.0 (+https://github.com/vedjr02/vedjr02)"
COUNT_RE = re.compile(r"^([\d,]+)\s+contributions?\b", re.IGNORECASE)


@dataclass(frozen=True)
class DayContribution:
    date: str  # YYYY-MM-DD
    count: int
    level: int  # GitHub 0–4 intensity


@dataclass(frozen=True)
class ContributionStats:
    total: int
    current_streak: int
    longest_streak: int
    best_day: str | None
    best_day_count: int


def contributions_url(username: str) -> str:
    return f"https://github.com/users/{username}/contributions"


def fetch_html(username: str, timeout: float = 30.0) -> str:
    """GET the public contributions calendar HTML."""
    url = contributions_url(username)
    log.info("Fetching %s", url)
    response = requests.get(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html",
        },
        timeout=timeout,
    )
    response.raise_for_status()
    return response.text


def parse_count_from_tooltip(text: str) -> int | None:
    """Extract contribution count from a calendar tooltip string."""
    text = text.strip()
    if not text:
        return None
    if text.lower().startswith("no contributions"):
        return 0
    match = COUNT_RE.match(text)
    if not match:
        return None
    return int(match.group(1).replace(",", ""))


def parse_contributions(html: str) -> list[DayContribution]:
    """Parse day cells + tooltips into a sorted list of contributions."""
    soup = BeautifulSoup(html, "html.parser")
    tips = {
        tip.get("for"): tip.get_text(" ", strip=True)
        for tip in soup.select("tool-tip")
        if tip.get("for")
    }

    days: list[DayContribution] = []
    for cell in soup.select(".ContributionCalendar-day"):
        day = cell.get("data-date")
        if not day:
            continue
        try:
            level = int(cell.get("data-level", "0"))
        except ValueError as exc:
            raise ValueError(f"Invalid data-level on {day}") from exc

        tip = tips.get(cell.get("id", ""), "")
        count = parse_count_from_tooltip(tip)
        if count is None:
            # Future / empty placeholder cells sometimes lack tooltips.
            count = 0 if level == 0 else None
        if count is None:
            log.warning("Could not parse count for %s (level=%s tip=%r)", day, level, tip)
            count = 0

        days.append(DayContribution(date=day, count=count, level=max(0, min(level, 4))))

    if not days:
        raise ValueError(
            "No contribution days found — GitHub HTML structure may have changed"
        )

    days.sort(key=lambda d: d.date)
    return days


def compute_stats(days: list[DayContribution], *, today: date | None = None) -> ContributionStats:
    """Compute total, streaks, and best day from daily counts."""
    today = today or datetime.now(timezone.utc).date()
    total = sum(d.count for d in days)

    best_day = None
    best_count = -1
    for day in days:
        if day.count > best_count:
            best_count = day.count
            best_day = day.date

    # Longest streak: consecutive days with count > 0
    longest = 0
    running = 0
    for day in days:
        if day.count > 0:
            running += 1
            longest = max(longest, running)
        else:
            running = 0

    # Current streak: walk backward from today (or latest day <= today)
    by_date = {d.date: d.count for d in days}
    cursor = today
    # If today isn't in the calendar yet, start from the last available day.
    if cursor.isoformat() not in by_date and days:
        cursor = date.fromisoformat(days[-1].date)

    current = 0
    while True:
        key = cursor.isoformat()
        if key not in by_date:
            break
        if by_date[key] > 0:
            current += 1
            cursor = date.fromordinal(cursor.toordinal() - 1)
            continue
        # Allow today to be empty without breaking a streak that ended yesterday.
        if current == 0 and cursor == today:
            cursor = date.fromordinal(cursor.toordinal() - 1)
            continue
        break

    return ContributionStats(
        total=total,
        current_streak=current,
        longest_streak=longest,
        best_day=best_day,
        best_day_count=max(best_count, 0),
    )


def build_payload(
    username: str,
    days: list[DayContribution],
    stats: ContributionStats,
) -> dict[str, Any]:
    """JSON-serializable document stored in data/contributions.json."""
    return {
        "username": username,
        "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": contributions_url(username),
        "stats": asdict(stats),
        "days": [asdict(day) for day in days],
    }


def fetch_and_save(username: str, output_path) -> dict[str, Any]:
    """End-to-end: fetch → parse → stats → write JSON.

    Skips rewriting the file when days + stats are unchanged so CI does not
    create empty daily commits solely due to a fresh fetched_at timestamp.
    """
    html = fetch_html(username)
    days = parse_contributions(html)
    stats = compute_stats(days)
    payload = build_payload(username, days, stats)

    output_path = Path(output_path)
    if output_path.is_file():
        try:
            previous = json.loads(output_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            previous = None
        if (
            isinstance(previous, dict)
            and previous.get("days") == payload["days"]
            and previous.get("stats") == payload["stats"]
            and previous.get("username") == payload["username"]
        ):
            log.info(
                "No contribution changes since %s — leaving %s untouched",
                previous.get("fetched_at", "unknown"),
                output_path,
            )
            return previous

    write_text(output_path, json.dumps(payload, indent=2) + "\n")
    log.info(
        "Wrote %s (%s days, total=%s, streak=%s, best=%s on %s)",
        output_path,
        len(days),
        stats.total,
        stats.current_streak,
        stats.best_day_count,
        stats.best_day,
    )
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch GitHub contributions (no token)")
    parser.add_argument("--username", default=None, help="Override config username")
    parser.add_argument("--output", default=None, help="Override output JSON path")
    args = parser.parse_args()

    config = load_config()
    username = args.username or str(config["github_username"])
    output = resolve_path(args.output or config["paths"]["contributions_json"])
    fetch_and_save(username, output)


if __name__ == "__main__":
    main()
