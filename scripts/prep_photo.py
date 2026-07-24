"""Prepare the profile photo for ASCII conversion.

Pipeline:
1. Load source image and apply EXIF orientation.
2. Remove background (rembg) for a clean silhouette.
3. Convert to grayscale and boost contrast.
4. Optionally sharpen edges slightly for ASCII clarity.
5. Write a transparent PNG for the ASCII generator.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageEnhance, ImageOps
from rembg import remove

from common import load_config, resolve_path, setup_logging

log = setup_logging()


def load_oriented_image(path: Path) -> Image.Image:
    """Open an image and normalize orientation using EXIF metadata."""
    image = Image.open(path)
    # ImageOps.exif_transpose returns a correctly rotated copy (or original).
    oriented = ImageOps.exif_transpose(image)
    return oriented.convert("RGBA")


def remove_background(image: Image.Image) -> Image.Image:
    """Isolate the subject; rembg returns RGBA with alpha matte."""
    log.info("Removing background (rembg) — first run may download a model…")
    result = remove(image)
    if not isinstance(result, Image.Image):
        result = Image.open(result)  # type: ignore[arg-type]
    return result.convert("RGBA")


def enhance_for_ascii(image: Image.Image) -> Image.Image:
    """Grayscale + contrast on RGB; preserve alpha from rembg."""
    alpha = image.getchannel("A")
    gray = image.convert("L")

    # Stronger contrast helps ASCII glyph mapping separate face/hoodie/edge.
    gray = ImageEnhance.Contrast(gray).enhance(1.45)
    gray = ImageEnhance.Brightness(gray).enhance(1.05)

    # Light unsharp-style boost via OpenCV for hair/edge detail.
    arr = np.array(gray, dtype=np.uint8)
    blurred = cv2.GaussianBlur(arr, (0, 0), sigmaX=1.0)
    sharpened = cv2.addWeighted(arr, 1.35, blurred, -0.35, 0)
    gray = Image.fromarray(sharpened)

    out = Image.merge("LA", (gray, alpha)).convert("RGBA")
    return out


def crop_to_alpha(image: Image.Image, padding: int = 8) -> Image.Image:
    """Trim transparent margins so the ASCII grid focuses on the subject."""
    alpha = np.array(image.getchannel("A"))
    ys, xs = np.where(alpha > 8)
    if len(xs) == 0 or len(ys) == 0:
        log.warning("No opaque pixels found after background removal")
        return image

    left = max(int(xs.min()) - padding, 0)
    top = max(int(ys.min()) - padding, 0)
    right = min(int(xs.max()) + padding + 1, image.width)
    bottom = min(int(ys.max()) + padding + 1, image.height)
    return image.crop((left, top, right, bottom))


def prepare_photo(source: Path, destination: Path) -> Path:
    """Run the full prep pipeline and write `destination`."""
    if not source.is_file():
        raise FileNotFoundError(f"Source photo not found: {source}")

    log.info("Loading %s", source)
    image = load_oriented_image(source)
    log.info("Oriented size: %sx%s", image.width, image.height)

    image = remove_background(image)
    image = enhance_for_ascii(image)
    image = crop_to_alpha(image)
    log.info("Processed size: %sx%s", image.width, image.height)

    destination.parent.mkdir(parents=True, exist_ok=True)
    image.save(destination, format="PNG", optimize=True)
    log.info("Wrote %s (%s bytes)", destination, destination.stat().st_size)
    return destination


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare photo for ASCII SVG")
    parser.add_argument(
        "--source",
        type=Path,
        default=None,
        help="Override source path from config",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Override output path from config",
    )
    args = parser.parse_args()

    config = load_config()
    source = args.source or resolve_path(config["paths"]["photo_source"])
    output = args.output or resolve_path(config["paths"]["photo_processed"])

    prepare_photo(source, output)


if __name__ == "__main__":
    main()
