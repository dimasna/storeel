"""Cut-outs drawn on a green screen and keyed out here.

SAM cuts out one thing it can name ("woman", "red denture case"); a scene of people with what they
sit on or hold (two people on a bench, servants with a tray) is many things, and a close-up of
hands has no whole thing to name. These are drawn on a flat green screen and keyed out locally:
the screen's colour is measured on the picture's border, alpha comes from how green a pixel is
compared with it, and the edges have the screen subtracted and any green spill removed.
"""

from __future__ import annotations

import numpy as np
from PIL import Image, ImageFilter

GREEN_SCREEN = (
    "Background: one perfectly flat, uniform pure green (#00FF00) screen filling the whole frame, with no"
    " floor, ground shadow, gradient, reflection or texture. Green appears nowhere on the subject."
)
GREEN_AGAIN = " The background must be the flat green screen described, nothing else."
MIN_SCREEN = 0.01  # of the border pixels: this much visible screen is enough to measure it
MIN_SUBJECT = 0.02  # of the picture: less than this left after keying is not a subject


def key_out_green(image: Image.Image) -> Image.Image | None:
    """The picture's subject as RGBA, cropped to it with a little room; None when the picture
    has no green screen to key out (almost none of its border is green) or nothing is left."""
    rgb = np.asarray(image.convert("RGB"), dtype=np.float32)
    dominance = rgb[..., 1] - np.maximum(rgb[..., 0], rgb[..., 2])
    edge = max(2, min(dominance.shape) // 100)
    border = np.zeros(dominance.shape, bool)
    border[:edge, :] = border[-edge:, :] = border[:, :edge] = border[:, -edge:] = True
    # A close-up (hands, a sleeve running off the frame) can cover most of the border; a little
    # visible screen on it is all that is needed to measure the screen.
    on_screen = border & (dominance > 80)
    if on_screen.sum() < max(20, MIN_SCREEN * border.sum()):
        return None
    screen = float(np.median(dominance[on_screen]))
    bg = np.median(rgb[on_screen], axis=0)
    t = np.clip(dominance / screen, 0, 1)
    alpha = np.clip((0.92 - t) / 0.84, 0, 1)
    soft = Image.fromarray((alpha * 255).round().astype(np.uint8)).filter(ImageFilter.GaussianBlur(0.6))
    alpha = np.asarray(soft, dtype=np.float32) / 255
    a = alpha[..., None]
    fg = np.clip((rgb - (1 - a) * bg) / np.maximum(a, 0.2), 0, 255)
    edge_px = alpha < 0.999
    cap = np.maximum(fg[..., 0], fg[..., 2])
    fg[..., 1] = np.where(edge_px, np.minimum(fg[..., 1], cap), fg[..., 1])  # despill
    if (alpha > 0.5).mean() < MIN_SUBJECT:
        return None
    out = Image.fromarray(np.dstack([fg, alpha[..., None] * 255]).round().astype(np.uint8), "RGBA")
    bbox = out.getchannel("A").point(lambda v: 255 if v > 12 else 0).getbbox()
    if bbox is None:
        return None
    pad = round(max(bbox[2] - bbox[0], bbox[3] - bbox[1]) * 0.02)
    return out.crop(
        (
            max(0, bbox[0] - pad),
            max(0, bbox[1] - pad),
            min(out.width, bbox[2] + pad),
            min(out.height, bbox[3] + pad),
        )
    )
