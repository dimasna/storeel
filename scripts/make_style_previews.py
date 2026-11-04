"""Cut the style examples into the loops and stills the web app shows (web/src/assets/styles).

The examples are renders of one part, one per look and theme, named <look>-<theme>.mp4 (made
through the studio itself: process the part once, then render it in each style, which is free).
Each becomes a few seconds of it, silent and small, cut from the same moments of every render so
only the style changes from one to the next, and a still from one of those moments.

    uv run python scripts/make_style_previews.py RENDERS --cuts 0.3-2.8,25.6-27.9,33.8-36.6 --still 26.6
"""

from __future__ import annotations

import argparse
import subprocess
from io import BytesIO
from pathlib import Path

from PIL import Image

OUT = Path(__file__).resolve().parent.parent / "web" / "src" / "assets" / "styles"
SIZE = (360, 640)  # twice a tile's width on a phone
FPS = 24


def loop(src: Path, dst: Path, cuts: list[tuple[float, float]]) -> None:
    """The cuts of `src`, one after the other, silent, at SIZE."""
    parts = [
        f"[0:v]trim=start={a:.3f}:end={b:.3f},setpts=PTS-STARTPTS,fps={FPS},"
        f"scale={SIZE[0]}:{SIZE[1]}:flags=lanczos,setsar=1[c{k}]"
        for k, (a, b) in enumerate(cuts)
    ]
    joined = "".join(f"[c{k}]" for k in range(len(cuts)))
    graph = ";".join(parts) + f";{joined}concat=n={len(cuts)}:v=1:a=0,format=yuv420p[v]"
    subprocess.run(
        [
            "ffmpeg", "-v", "error", "-y", "-i", str(src), "-filter_complex", graph, "-map", "[v]", "-an",
            "-c:v", "libx264", "-preset", "slow", "-crf", "29", "-profile:v", "high",
            "-movflags", "+faststart", str(dst),
        ],
        check=True,
    )  # fmt: skip


def still(src: Path, dst: Path, at: float) -> None:
    png = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", f"{at:.3f}", "-i", str(src), "-frames:v", "1", "-f", "image2pipe",
         "-vcodec", "png", "-"],
        capture_output=True, check=True,
    ).stdout  # fmt: skip
    frame = Image.open(BytesIO(png)).convert("RGB").resize(SIZE, Image.LANCZOS)
    frame.save(dst, "WEBP", quality=74, method=6)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("renders", type=Path, help="a folder of <look>-<theme>.mp4 renders")
    parser.add_argument("--cuts", required=True, help="the moments to keep, in seconds: a-b,c-d,...")
    parser.add_argument("--still", type=float, required=True, help="the still's moment, in seconds")
    parser.add_argument(
        "--still-for", default="", help="another moment for a look's stills, e.g. dalang=35 (comma-separated)"
    )
    args = parser.parse_args()
    cuts = [tuple(float(x) for x in part.split("-")) for part in args.cuts.split(",")]
    still_at = {look: float(t) for look, t in (part.split("=") for part in args.still_for.split(",") if part)}
    OUT.mkdir(parents=True, exist_ok=True)
    total = 0
    for src in sorted(args.renders.glob("*-*.mp4")):
        look, theme = src.stem.split("-", 1)
        if look not in ("dalang", "scene", "studio") or theme == "auto":
            continue
        video, picture = OUT / f"{src.stem}.mp4", OUT / f"{src.stem}.webp"
        loop(src, video, cuts)  # type: ignore[arg-type]
        still(src, picture, still_at.get(look, args.still))
        size = video.stat().st_size + picture.stat().st_size
        total += size
        print(f"{src.stem}: {video.stat().st_size / 1000:.0f} KB + {picture.stat().st_size / 1000:.0f} KB")
    print(f"total {total / 1e6:.1f} MB in {OUT}")


if __name__ == "__main__":
    main()
