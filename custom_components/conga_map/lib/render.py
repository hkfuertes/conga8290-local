"""PNG renderer — obstacles, room palette, dock marker. Pillow only."""
from __future__ import annotations

from PIL import Image

from .mapfile import decode_full

PALETTE = [
    (0xFD, 0xE4, 0xCF), (0x8E, 0xEC, 0xF5), (0xCF, 0xBA, 0xF0), (0xF1, 0xC0, 0xE8),
    (0xA3, 0xC4, 0xF3), (0x98, 0xF5, 0xE1), (0xFF, 0xCF, 0xD2), (0x90, 0xDB, 0xF4),
    (0xE1, 0xC1, 0xEB), (0x8E, 0xCC, 0xF5), (0xED, 0xDD, 0xDE), (0xA3, 0xB8, 0xF3),
    (0xEF, 0xCF, 0xE1), (0xB2, 0xF2, 0xBE), (0xAE, 0xE6, 0xF8), (0x90, 0xC2, 0xF4),
]
FREE = (0xF2, 0xF2, 0xF2, 255)
OBSTACLE = (0x55, 0x55, 0x55, 255)  # #555
DOCK = (0x00, 0x66, 0xFF, 255)


def render_png(raw: bytes, path: str) -> str:
    """Decode raw map bytes and write the PNG next to decode_full's grid."""
    md = decode_full(raw)
    hd = md["hd"]
    w, h, grid = hd["width"], hd["height"], md["grid"]
    v2 = hd["version"] >= 2
    px = []
    for b in grid:
        t = b & 7
        if v2 and t in (2, 7):
            r, g, bl = PALETTE[((b >> 3) & 31) % 16]
            if t == 2:  # carpet: darken
                r, g, bl = r // 2, g // 2, bl // 2
            px.append((r, g, bl, 255))
        elif t == 1:
            px.append(OBSTACLE)
        else:
            px.append(FREE)
    img = Image.new("RGBA", (w, h))
    img.putdata(px)

    # dock marker
    dx, dy = int(hd["charge_x"] + 0.5), int(hd["charge_y"] + 0.5)
    if 0 <= dx < w and 0 <= dy < h:
        for ox, oy in ((0, 0), (1, 0), (0, 1), (1, 1), (-1, 0), (0, -1)):
            x, y = dx + ox, dy + oy
            if 0 <= x < w and 0 <= y < h:
                img.putpixel((x, y), DOCK)
    img.save(path, "PNG")
    return path


if __name__ == "__main__":
    import glob

    files = sorted(glob.glob("maps/*.bin"))
    assert files, "no maps/*.bin found — run from repo root"
    for f in files:
        print(render_png(open(f, "rb").read(), f.removesuffix(".bin") + ".test.png"))
