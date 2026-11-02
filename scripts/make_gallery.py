"""Draw the home page's gallery with Muse Image: one story moment per picture look.

Each tile of the gallery is a mock frame of a novel part, drawn here once and committed as a
small WebP under web/src/assets/gallery/. The words on a tile (part, title, caption) are laid
over the picture by the page, so the pictures carry no text.

    MODEL_API_KEY=... uv run python scripts/make_gallery.py            # draw what is missing
    MODEL_API_KEY=... uv run python scripts/make_gallery.py anime-rooftop --force
"""

from __future__ import annotations

import base64
import io
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PIL import Image

from storeel.meta.client import MetaClient
from storeel.pipeline.assets import NO_TEXT, PORTRAIT, STYLES

OUT = Path(__file__).resolve().parent.parent / "web" / "src" / "assets" / "gallery"
FRAME = (
    "Vertical frame, cropped to 9:16 at the sides: keep the main subject centred and in the upper two"
    " thirds; the bottom third sits under captions, so keep it simple and dark enough for white text."
)

# id -> (look, the moment to draw). The ids match web/src/lib/gallery.ts.
TILES: dict[str, tuple[str, str]] = {
    "palace-promise": (
        "illustration",
        "A young Javanese princess in an elegant dark red kebaya and a traditional sanggul bun stands alone"
        " in a lantern-lit royal pavilion at night, holding back tears; behind her, out of focus, a prince"
        " walks away with another woman. Warm lantern light, deep shadows, a heartbroken mood.",
    ),
    "gull-point": (
        "watercolor",
        "A girl in a yellow sweater and a red scarf climbs the spiral iron stairs inside an old lighthouse"
        " at night, holding a swinging lantern, looking down in fear; through a small window a storm"
        " lashes the sea.",
    ),
    "anime-letter": (
        "anime",
        "A high-school girl in a sailor uniform stands on a school rooftop at sunset, clutching an"
        " unopened pink letter to her chest, her hair and skirt blown by the wind, cherry blossom petals"
        " drifting, the city below glowing orange.",
    ),
    "noir-umbrella": (
        "cinematic",
        "A detective in a long grey coat stands under a single streetlight on a wet cobblestone street at"
        " night in the rain, looking at a red umbrella lying open on the ground; fog, reflections, a"
        " tense noir mood.",
    ),
    "comic-heist": (
        "comic",
        "A masked thief in a black suit leaps between two skyscraper rooftops at night, holding a glowing"
        " blue gem, searchlights sweeping the sky behind; dynamic action pose seen from below.",
    ),
    "dragon-queen": (
        "realistic_3d",
        "A young queen with a silver crown and a dark blue cloak stands defiantly in a vast stone throne"
        " hall, facing an enormous black dragon whose head lowers towards her; torchlight, embers in"
        " the air.",
    ),
    "chef-cat": (
        "3d",
        "A chubby orange cat wearing a tiny white chef hat sits proudly on a kitchen table next to a"
        " half-eaten three-tier wedding cake, frosting on its whiskers, flour everywhere; a shocked"
        " grandmother in an apron in the doorway behind.",
    ),
    "music-box": (
        "illustration",
        "A girl in pyjamas holding a flashlight stands at the top of narrow attic stairs at midnight,"
        " staring at an open antique music box glowing softly on a dusty trunk; moonlight through a"
        " round window, an eerie, quiet mood.",
    ),
    "villain-isekai": (
        "anime",
        "A young man in a modern grey hoodie wakes up inside a glowing golden magic circle on the floor"
        " of a gothic castle hall, wearing a villain's black cape and crown that he stares at in shock;"
        " knights with swords surround him.",
    ),
    "contract-marriage": (
        "cinematic",
        "A young woman in a white blouse stands in a dark glass-walled penthouse office at night,"
        " holding a contract and a pen, rain streaking the windows over the city lights; a man in a black"
        " suit waits by the window, his back to her.",
    ),
}


def draw(client: MetaClient, tile: str) -> str:
    look, moment = TILES[tile]
    text = f"{moment} Style: {STYLES[look]}. {FRAME} {NO_TEXT}"
    result = client.responses(
        {
            "model": "muse-image-1.0",
            "store": False,
            "input": [{"type": "message", "role": "user", "content": [{"type": "input_text", "text": text}]}],
            "tools": [
                {
                    "type": "image_generation",
                    "size": PORTRAIT,
                    "output_format": "png",
                    "reasoning_strength": "high",
                    "enable_image_search": False,
                    "enable_web_search": False,
                    "enable_shell": False,
                }
            ],
        }
    )
    if not result.images:
        return f"{tile}: no image"
    with Image.open(io.BytesIO(base64.b64decode(result.images[0]))) as image:
        rgb = image.convert("RGB")
    # 2:3 to 9:16, from the centre, then small enough for a gallery tile.
    width = round(rgb.height * 9 / 16)
    left = (rgb.width - width) // 2
    tile_image = rgb.crop((left, 0, left + width, rgb.height)).resize((576, 1024), Image.LANCZOS)
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{tile}.webp"
    tile_image.save(path, "WEBP", quality=78, method=6)
    return f"{tile}: {path.stat().st_size // 1024} KB in {result.seconds:.0f}s"


def main() -> None:
    key = os.environ.get("MODEL_API_KEY", "").strip()
    if not key:
        sys.exit("set MODEL_API_KEY")
    force = "--force" in sys.argv
    wanted = [a for a in sys.argv[1:] if not a.startswith("--")] or list(TILES)
    todo = [t for t in wanted if force or not (OUT / f"{t}.webp").exists()]
    client = MetaClient(key)
    with ThreadPoolExecutor(4) as pool:
        for line in pool.map(lambda t: draw(client, t), todo):
            print(line, flush=True)


if __name__ == "__main__":
    main()
