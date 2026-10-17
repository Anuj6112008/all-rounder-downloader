"""Generate PWA PNG icons (192, 512, maskable-512) into public/icons.

Draws the IGDesk brand mark to match public/icons/favicon.svg:
Instagram-gradient tile, white camera body, gradient lens ring with a
download arrow inside, and a small gradient flash dot.

Drawn at 4x and downscaled (LANCZOS) for antialiased edges. Run once:
    python scripts/gen_icons.py
"""
import os

from PIL import Image, ImageDraw

OUT = os.path.join(os.path.dirname(__file__), "..", "public", "icons")
os.makedirs(OUT, exist_ok=True)

SS = 4  # supersampling factor

STOPS = [
    (0.00, (254, 218, 117)),   # #feda75
    (0.30, (250, 126, 30)),    # #fa7e1e
    (0.60, (214, 41, 118)),    # #d62976
    (0.85, (150, 47, 191)),    # #962fbf
    (1.00, (79, 91, 213)),     # #4f5bd5
]


def _gradient(size):
    """Instagram brand gradient: yellow -> orange -> pink -> purple -> blue."""
    img = Image.new("RGB", (size, size))
    px = img.load()
    for y in range(size):
        for x in range(size):
            t = (x + y) / (2 * size)
            for i in range(len(STOPS) - 1):
                t0, c0 = STOPS[i]
                t1, c1 = STOPS[i + 1]
                if t0 <= t <= t1:
                    f = 0 if t1 == t0 else (t - t0) / (t1 - t0)
                    px[x, y] = tuple(int(c0[k] + (c1[k] - c0[k]) * f) for k in range(3))
                    break
    return img


def _brand(size, rounded=True, scale=1.0):
    """RGBA icon of the IGDesk mark. `scale` shrinks the artwork (maskable)."""
    s = size * SS

    def X(v):
        """Map a 64-grid x coordinate to supersampled pixels."""
        return s / 2 + (v - 32) * (s / 64) * scale

    def Y(v):
        return X(v)

    def L(v):
        return v * (s / 64) * scale

    bg = _gradient(s).convert("RGBA")

    # Tile shape: rounded square, or full-bleed (maskable applies its own mask).
    mask = Image.new("L", (s, s), 0)
    md = ImageDraw.Draw(mask)
    if rounded:
        md.rounded_rectangle([0, 0, s - 1, s - 1], radius=int(s * 0.266), fill=255)
    else:
        md.rectangle([0, 0, s - 1, s - 1], fill=255)
    bg.putalpha(mask)

    d = ImageDraw.Draw(bg)

    # White camera: viewfinder bump (rounded top corners; body overlaps the
    # square bottom corners) + body.
    d.rounded_rectangle(
        [X(23.5), Y(11), X(40.5), Y(20)], radius=L(3.5), fill="white"
    )
    d.rounded_rectangle(
        [X(8.5), Y(18), X(55.5), Y(47)], radius=L(7), fill="white"
    )

    # Gradient-colored lens ring + download arrow + flash dot, composited
    # through a mask (PIL cannot stroke/fill with a gradient directly).
    ring_layer = _gradient(s).convert("RGBA")
    ring_mask = Image.new("L", (s, s), 0)
    rd = ImageDraw.Draw(ring_mask)

    cx, cy = X(32), Y(33)
    r_out, r_in = L(11.5), L(7.5)
    rd.ellipse([cx - r_out, cy - r_out, cx + r_out, cy + r_out], fill=255)
    rd.ellipse([cx - r_in, cy - r_in, cx + r_in, cy + r_in], fill=0)

    aw = L(3.4)
    top, bot = Y(28.4), Y(37)
    rd.line([cx, top, cx, bot], fill=255, width=int(aw))
    rd.line(
        [(X(27.9), Y(32.9)), (cx, bot), (X(36.1), Y(32.9))],
        fill=255, width=int(aw), joint="curve",
    )

    dx, dy, dr = X(46.5), Y(24.5), L(2.4)
    rd.ellipse([dx - dr, dy - dr, dx + dr, dy + dr], fill=255)

    bg.paste(ring_layer, (0, 0), ring_mask)

    return bg.resize((size, size), Image.LANCZOS)


def main():
    _brand(192).save(os.path.join(OUT, "icon-192.png"))
    _brand(512).save(os.path.join(OUT, "icon-512.png"))
    # maskable: full-bleed tile, artwork inside the ~80% safe zone
    _brand(512, rounded=False, scale=0.82).save(
        os.path.join(OUT, "icon-maskable-512.png")
    )
    print("icons written to", os.path.abspath(OUT))


if __name__ == "__main__":
    main()
