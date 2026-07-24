# Building the terminal profile README

Local art is generated with Python and committed to the repo. GitHub Actions
refreshes only the contribution heatmap daily (no token, no third-party stats).

## Requirements

- Python 3.11+ recommended (3.9 works locally if that is all you have)
- Full local pipeline: `scripts/requirements.txt`
- CI / heatmap-only: `scripts/requirements-ci.txt`

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r scripts/requirements.txt
```

Place your source photo at `data/photo/source.jpg` (already configured).

Edit personal copy, theme, and paths in `config/profile.yaml`.

## Commands

| Command | What it does |
|---------|----------------|
| `python scripts/prep_photo.py` | EXIF rotate, rembg, contrast → `data/photo/processed.png` |
| `python scripts/make_ascii_svg.py` | Animated ASCII portrait → `assets/avi-ascii.svg` |
| `python scripts/make_info_card.py` | Neofetch card → `assets/info-card.svg` |
| `python scripts/fetch_contributions.py` | Public contributions → `data/contributions.json` |
| `python scripts/render_heatmap_svg.py` | Heatmap SVG → `assets/contrib-heatmap.svg` |
| `python scripts/build_all.py` | Run the full pipeline |
| `python scripts/build_all.py --skip-photo` | Reuse processed photo |
| `python scripts/build_all.py --heatmap-only` | Same work as CI |

Open any `assets/*.svg` in a browser to preview SMIL animations.

## GitHub Actions

`.github/workflows/update-profile-art.yml` runs daily at 06:00 UTC and on
manual dispatch. It updates only:

- `data/contributions.json`
- `assets/contrib-heatmap.svg`

and commits when those files change. There is no `push` trigger, so the bot
commit cannot loop the workflow.

`fetch_contributions.py` leaves `contributions.json` untouched when days/stats
are unchanged, and the heatmap footer uses the date range (not a wall-clock
timestamp) so empty days do not force noisy commits.

## Design notes

- SVGs use SMIL (`<animate>`), not JavaScript — GitHub strips JS.
- ASCII uses luma + Sobel edges with percentile stretch so dark clothing still maps across the glyph ramp.
- Contributions are scraped from the public calendar HTML (no PAT).
- Photo/ASCII generation stays local because `rembg` / OpenCV are heavy for CI.
