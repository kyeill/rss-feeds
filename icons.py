"""The app's icons, drawn by pixel maths and written as PNGs.

There is no image library on this machine (the same constraint games-history's
icons.py works under), so every shape is a rectangle, disc or capsule resolved
per pixel with 4x4 supersampling for smooth edges, then deflated by hand.

The mark is the page itself: a spine with a dot per team, in tab order and
team colour (Tigers orange, Lions blue, Pistons teal, Red Wings red, Cavaliers
gold), each with a headline bar beside it. Everything sits inside the
maskable safe circle (radius 0.4 about the centre), so Android can cut the
icon to any shape -- that is what makes it an adaptive icon.

    python icons.py

writes docs/icon-192.png, icon-512.png (full-bleed, "any maskable"),
icon-180.png (iPhone home screen) and icon-mono-512.png (Android 13+ themed
icons: white on transparent, recoloured by the launcher). The browser-tab
favicon is an SVG drawn by the page itself, in the open tab's colour.
"""

import os
import struct
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "docs")

BG = (0x0D, 0x10, 0x13)            # the page's dark ground
SPINE = (0x3A, 0x43, 0x4D)
BAR = (0xDC, 0xE1, 0xE7)
TEAMS = [(0xFA, 0x46, 0x16), (0x00, 0x76, 0xB6), (0x00, 0xA3, 0xAD),
         (0xCE, 0x11, 0x26), (0xFD, 0xBB, 0x30)]

SPINE_X, ROW0, ROW_STEP = 0.346, 0.27, 0.115
DOT_R, BAR_H, BAR_X0 = 0.046, 0.044, 0.43
BAR_X1 = [0.72, 0.61, 0.68, 0.56, 0.66]     # headline lengths, ragged like a feed


def capsule(u, v, x0, x1, cy, h):
    r = h / 2
    if x0 + r <= u <= x1 - r:
        return abs(v - cy) <= r
    cx = x0 + r if u < x0 + r else x1 - r
    return (u - cx) ** 2 + (v - cy) ** 2 <= r * r


def shape(u, v):
    """The colour of the mark at (u, v) in unit coordinates, or None."""
    for i, colour in enumerate(TEAMS):
        cy = ROW0 + i * ROW_STEP
        if (u - SPINE_X) ** 2 + (v - cy) ** 2 <= DOT_R ** 2:
            return colour
        if capsule(u, v, BAR_X0, BAR_X1[i], cy, BAR_H):
            return BAR
    if abs(u - SPINE_X) <= 0.011 and ROW0 <= v <= ROW0 + 4 * ROW_STEP:
        return SPINE
    return None


def render(size, mono=False, scale=1.0, ss=4):
    """RGB (or RGBA for the monochrome mask) rows, supersampled. `scale` grows
    the mark about the centre: the iPhone icon is only rounded, never cut to a
    circle, so it can fill more of the square than the maskable ones."""
    rows = []
    n = ss * ss
    for y in range(size):
        row = bytearray([0])
        for x in range(size):
            r = g = b = a = 0
            for sy in range(ss):
                for sx in range(ss):
                    u = 0.5 + ((x + (sx + 0.5) / ss) / size - 0.5) / scale
                    v = 0.5 + ((y + (sy + 0.5) / ss) / size - 0.5) / scale
                    c = shape(u, v)
                    if mono:
                        a += 255 if c is not None else 0
                    else:
                        c = c or BG
                        r += c[0]; g += c[1]; b += c[2]
            row += bytes([255, 255, 255, a // n]) if mono else bytes([r // n, g // n, b // n])
        rows.append(bytes(row))
    return rows


def png(size, mono=False, scale=1.0):
    raw = zlib.compress(b"".join(render(size, mono, scale)), 9)

    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data +
                struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))
    return (b"\x89PNG\r\n\x1a\n" +
            chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6 if mono else 2, 0, 0, 0)) +
            chunk(b"IDAT", raw) + chunk(b"IEND", b""))


if __name__ == "__main__":
    for name, size, mono, scale in (("icon-192", 192, False, 1.0), ("icon-512", 512, False, 1.0),
                                    ("icon-180", 180, False, 1.25), ("icon-mono-512", 512, True, 1.0)):
        with open(os.path.join(OUT, name + ".png"), "wb") as f:
            f.write(png(size, mono, scale))
        print("docs/%s.png" % name)
