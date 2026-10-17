"""Generate PWA PNG icons (192, 512, maskable-512) into public/icons.

Draws a rounded gradient tile with a download arrow. Run once:
    python scripts/gen_icons.py
"""
import os

from PIL import Image, ImageDraw

OUT = os.path.join(os.path.dirname(__file__), "..", "public", "icons")
os.makedirs(OUT, exist_ok=True)


def _gradient(size):
    img = Image.new("RGB", (size, size))
    c1, c2 = (79, 140, 255), (124, 92, 255)
    for y in range(size):
        for x in range(size):
            t = (x + y) / (2 * size)
            img.putpixel((x, y), tuple(int(c1[i] + (c2[i] - c1[i]) * t) for i in range(3)))
    return img


def _draw_arrow(size, pad_frac, radius_frac, bg=None):
    """Return an RGBA icon of a download arrow on a rounded gradient tile."""
    img = _gradient(size).convert("RGBA")
    mask = Image.new("L", (size, size), 0)
    md = ImageDraw.Draw(mask)
    r = int(size * radius_frac)
    md.rounded_rectangle([0, 0, size - 1, size - 1], radius=r, fill=255)
    img.putalpha(mask)

    d = ImageDraw.Draw(img)
    pad = int(size * pad_frac)
    cx = size // 2
    top = pad
    bottom = size - pad
    shaft_w = max(4, int(size * 0.11))
    head_w = int(size * 0.34)
    head_h = int(size * 0.22)
    mid_y = bottom - head_h - int(size * 0.10)

    d.line([(cx, top), (cx, mid_y)], fill="white", width=shaft_w)
    d.polygon([(cx - head_w // 2, mid_y), (cx + head_w // 2, mid_y), (cx, bottom - int(size * 0.10))],
              fill="white")
    bar_y = bottom - int(size * 0.02)
    d.line([(cx - head_w, bar_y), (cx + head_w, bar_y)], fill="white", width=shaft_w)
    return img


def main():
    _draw_arrow(192, 0.26, 0.22).save(os.path.join(OUT, "icon-192.png"))
    _draw_arrow(512, 0.26, 0.22).save(os.path.join(OUT, "icon-512.png"))
    # maskable: keep artwork inside the ~80% safe zone
    _draw_arrow(512, 0.34, 0.0).save(os.path.join(OUT, "icon-maskable-512.png"))
    print("icons written to", os.path.abspath(OUT))


if __name__ == "__main__":
    main()
