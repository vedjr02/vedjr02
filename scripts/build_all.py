"""One-shot local rebuild of all profile art.

Examples:
  python scripts/build_all.py              # full pipeline
  python scripts/build_all.py --heatmap-only
  python scripts/build_all.py --skip-photo # reuse processed.png
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow `python scripts/build_all.py` to import sibling modules.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import load_config, resolve_path, setup_logging  # noqa: E402
from fetch_contributions import fetch_and_save  # noqa: E402
from make_ascii_svg import generate as generate_ascii  # noqa: E402
from make_info_card import generate as generate_info_card  # noqa: E402
from prep_photo import prepare_photo  # noqa: E402
from render_heatmap_svg import generate as generate_heatmap  # noqa: E402

log = setup_logging()


def build_all(*, skip_photo: bool, heatmap_only: bool) -> None:
    config = load_config()

    if heatmap_only:
        log.info("Heatmap-only rebuild")
        fetch_and_save(
            str(config["github_username"]),
            resolve_path(config["paths"]["contributions_json"]),
        )
        generate_heatmap(config)
        log.info("Done")
        return

    if not skip_photo:
        prepare_photo(
            resolve_path(config["paths"]["photo_source"]),
            resolve_path(config["paths"]["photo_processed"]),
        )
    else:
        processed = resolve_path(config["paths"]["photo_processed"])
        if not processed.is_file():
            raise FileNotFoundError(
                f"--skip-photo set but missing {processed}. Run without the flag once."
            )
        log.info("Skipping photo prep; using %s", processed)

    generate_ascii(config)
    generate_info_card(config)
    fetch_and_save(
        str(config["github_username"]),
        resolve_path(config["paths"]["contributions_json"]),
    )
    generate_heatmap(config)
    log.info("Full rebuild complete")


def main() -> None:
    parser = argparse.ArgumentParser(description="Rebuild profile art assets")
    parser.add_argument(
        "--skip-photo",
        action="store_true",
        help="Reuse data/photo/processed.png (skip rembg)",
    )
    parser.add_argument(
        "--heatmap-only",
        action="store_true",
        help="Only refresh contributions.json + contrib-heatmap.svg",
    )
    args = parser.parse_args()
    build_all(skip_photo=args.skip_photo, heatmap_only=args.heatmap_only)


if __name__ == "__main__":
    main()
