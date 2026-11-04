"""Cut the effect examples the home page's showcase plays (web/src/assets/effects).

Each effect is shown by a few seconds of the example part where it happens, cut from the style
example renders (see make_style_previews.py; every render is the same part, so the moments are
the same in each): the title behind the speaker, the word-by-word captions, the punch-in, the
step back under a picture, the spotlight at the cliffhanger, the living pictures, the theme's
particles, horror's echo, and the captions translated. Each becomes a small silent loop and a
still from its middle.

    uv run python scripts/make_effect_previews.py RENDERS [--translated part-id.mp4]
"""

from __future__ import annotations

import argparse
from pathlib import Path

from make_style_previews import loop, still

OUT = Path(__file__).resolve().parent.parent / "web" / "src" / "assets" / "effects"

# id: (render, start, end): seconds of the example part where the effect shows.
EFFECTS: dict[str, tuple[str, float, float]] = {
    "title": ("dalang-horror", 0.2, 3.3),
    "captions": ("dalang-drama", 3.6, 6.9),
    "punch": ("dalang-none", 7.4, 10.6),
    "step-back": ("dalang-romance", 12.6, 16.4),
    "spotlight": ("dalang-none", 40.2, 43.6),
    "living": ("studio-drama", 21.0, 24.6),
    "particles": ("studio-legend", 26.0, 29.6),
    "echo": ("dalang-horror", 5.8, 8.2),
    "translate": ("translated", 4.0, 7.6),
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("renders", type=Path, help="the folder of <look>-<theme>.mp4 renders")
    parser.add_argument("--translated", type=Path, help="a render of the part with translated captions")
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    total = 0
    for name, (render, start, end) in EFFECTS.items():
        src = args.translated if render == "translated" else args.renders / f"{render}.mp4"
        if src is None or not src.exists():
            print(f"{name}: no {render} render, skipped")
            continue
        video, picture = OUT / f"{name}.mp4", OUT / f"{name}.webp"
        loop(src, video, [(start, end)])
        still(src, picture, (start + end) / 2)
        size = video.stat().st_size + picture.stat().st_size
        total += size
        print(f"{name}: {video.stat().st_size / 1000:.0f} KB + {picture.stat().st_size / 1000:.0f} KB")
    print(f"total {total / 1e6:.1f} MB in {OUT}")


if __name__ == "__main__":
    main()
