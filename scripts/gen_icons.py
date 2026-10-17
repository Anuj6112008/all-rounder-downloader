"""Generate PWA PNG icons (192, 512, maskable-512) into public/icons.

Draws a rounded gradient tile with a download arrow. Run once:
    python scripts/gen_icons.py
"""
import os

from PIL import Image, ImageDraw

OUT = os.path.join(os.path.dirname(__file__), "..", "public", "icons")
os.makedirs(OUT, exist_ok=True)


def _gradient(size):
    """Instagram brand gradient: yellow -> orange -> pink -> purple -> blue."""
    img = Image.new("RGB", (size, size))
    stops = [
        (0.00, (254, 218, 117)),   # #feda75
        (0.30, (250, 126, 30)),    # #fa7e1e
        (0.60, (214, 41, 118)),    # #d62976
        (0.85, (150, 47, 191)),    # #962fbf
        (1.00, (79, 91, 213)),     # #4f5bd5
    ]
    for y in range(size):
        for x in range(size):
            t = (x + y) / (2 * size)
            for i in range(len(stops) - 1):
                t0, c0 = stops[i]
                t1, c1 = stops[i + 1]
                if t0 <= t <= t1:
                    f = 0 if t1 == t0 else (t - t0) / (t1 - t0)
                    img.putpixel((x, y), tuple(int(c0[k] + (c1[k] - c0[k]) * f) for k in range(3)))
                    break
    return img


def _draw_arrow(size, pad_frac, radius_frac, bg=None):
    """Return an RGBA icon of a rounded-square + camera glyph (Instagram mark)."""
    img = _gradient(size).convert("RGBA")
    mask = Image.new("L", (size, size), 0)
    md = ImageDraw.Draw(mask)
    r = int(size * radius_frac)
    md.rounded_rectangle([0, 0, size - 1, size - 1], radius=r, fill=255)
    img.putalpha(mask)

    d = ImageDraw.Draw(img)
    pad = int(size * pad_frac)
    box = [pad, pad, size - pad, size - pad]
    sw = max(4, int(size * 0.07))
    d.rounded_rectangle(box, radius=int(size * 0.12), outline="white", width=sw)
    r_out = (size - 2 * pad) // 3
    cx = cy = size // 2
    d.ellipse([cx - r_out, cy - r_out, cx + r_out, cy + r_out], outline="white", width=sw)
    dr = max(3, int(size * 0.05))
    dx = pad + int((size - 2 * pad) * 0.78)
    dy = pad + int((size - 2 * pad) * 0.24)
    d.ellipse([dx - dr, dy - dr, dx + dr, dy + dr], fill="white")
    return img


def main():
    _draw_arrow(192, 0.26, 0.22).save(os.path.join(OUT, "icon-192.png"))
    _draw_arrow(512, 0.26, 0.22).save(os.path.join(OUT, "icon-512.png"))
    # maskable: keep artwork inside the ~80% safe zone
    _draw_arrow(512, 0.34, 0.0).save(os.path.join(OUT, "icon-maskable-512.png"))
    print("icons written to", os.path.abspath(OUT))


if __name__ == "__main__":
    main()
