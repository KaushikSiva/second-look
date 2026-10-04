#!/usr/bin/env python3
"""Generate Second Look toolbar icons (16/48/128 PNG) with only the stdlib.

Design: rounded square with a violet→blue→teal diagonal gradient, a white lens ring
and an off-center pupil ("take a second look"). 4x4 supersampling for anti-aliasing.
Usage: python3 scripts/make_icons.py   (run from extension/)
"""
import math
import os
import struct
import zlib

STOPS = [(0.0, (0x8B, 0x7C, 0xFF)), (0.55, (0x5B, 0x8C, 0xFF)), (1.0, (0x4F, 0xD1, 0xC5))]


def grad(t):
    t = max(0.0, min(1.0, t))
    for (a, ca), (b, cb) in zip(STOPS, STOPS[1:]):
        if t <= b:
            k = (t - a) / (b - a)
            return tuple(ca[i] + (cb[i] - ca[i]) * k for i in range(3))
    return STOPS[-1][1]


def inside_rrect(x, y, r):
    # unit square [0,1]^2 with corner radius r
    cx = min(max(x, r), 1 - r)
    cy = min(max(y, r), 1 - r)
    return (x - cx) ** 2 + (y - cy) ** 2 <= r * r


def sample(x, y, size):
    """Return (r,g,b,a) in 0..1 floats for a point in unit space."""
    corner = 0.25 if size > 16 else 0.22
    if not inside_rrect(x, y, corner):
        return (0, 0, 0, 0)
    r, g, b = grad((x + y) / 2)
    color = (r / 255, g / 255, b / 255)
    # lens ring
    ring_r = 0.27 if size > 16 else 0.28
    ring_w = 0.085 if size > 16 else 0.11
    d = math.hypot(x - 0.5, y - 0.5)
    if abs(d - ring_r) <= ring_w / 2:
        return (1, 1, 1, 1)
    # pupil, offset up-right
    pr = 0.10 if size > 16 else 0.12
    if math.hypot(x - 0.555, y - 0.445) <= pr:
        return (1, 1, 1, 1)
    return (*color, 1)


def render(size, ss=4):
    rows = []
    for py in range(size):
        row = bytearray([0])  # filter type 0
        for px in range(size):
            acc = [0.0, 0.0, 0.0, 0.0]
            for sy in range(ss):
                for sx in range(ss):
                    x = (px + (sx + 0.5) / ss) / size
                    y = (py + (sy + 0.5) / ss) / size
                    r, g, b, a = sample(x, y, size)
                    acc[0] += r * a
                    acc[1] += g * a
                    acc[2] += b * a
                    acc[3] += a
            n = ss * ss
            a = acc[3] / n
            if a > 0:
                rgb = [int(round(acc[i] / acc[3] * 255)) for i in range(3)]
            else:
                rgb = [0, 0, 0]
            row += bytes(rgb + [int(round(a * 255))])
        rows.append(bytes(row))
    return b"".join(rows)


def png(size, raw):
    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    out = os.path.join(here, "..", "icons")
    os.makedirs(out, exist_ok=True)
    for s in (16, 32, 48, 128):
        with open(os.path.join(out, f"icon{s}.png"), "wb") as f:
            f.write(png(s, render(s)))
        print("wrote", f"icons/icon{s}.png")


if __name__ == "__main__":
    main()
