#!/usr/bin/env python3
"""Erzeugt plugin/icons/icon_{64,128,256,512}.png (Mülltonne auf grünem Grund) – nur Standardbibliothek."""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GREEN = (46, 125, 50)
WHITE = (255, 255, 255)


def inside(x: float, y: float) -> tuple:
    """Farbe (RGBA) an Position x, y im Bereich 0..1."""
    # abgerundetes Quadrat als Hintergrund
    r = 0.18
    cx = min(max(x, r), 1 - r)
    cy = min(max(y, r), 1 - r)
    if (x - cx) ** 2 + (y - cy) ** 2 > r * r:
        return (0, 0, 0, 0)
    color = GREEN + (255,)
    # Griff
    if 0.42 <= x <= 0.58 and 0.18 <= y <= 0.26 and not (0.46 <= x <= 0.54 and y >= 0.21):
        return WHITE + (255,)
    # Deckel
    if 0.24 <= x <= 0.76 and 0.27 <= y <= 0.34:
        return WHITE + (255,)
    # Tonne (nach unten schmaler) mit drei Rillen
    if 0.37 <= y <= 0.82:
        t = (y - 0.37) / 0.45
        half = 0.22 - 0.04 * t
        if abs(x - 0.5) <= half:
            for gx in (0.41, 0.5, 0.59):
                if abs(x - gx) <= 0.018 and 0.44 <= y <= 0.75:
                    return color
            return WHITE + (255,)
    return color


def render(size: int) -> bytes:
    ss = 4  # Kantenglättung durch Überabtastung
    rows = []
    for py in range(size):
        row = bytearray([0])
        for px in range(size):
            acc = [0, 0, 0, 0]
            for sy in range(ss):
                for sx in range(ss):
                    c = inside((px + (sx + 0.5) / ss) / size, (py + (sy + 0.5) / ss) / size)
                    for i in range(3):
                        acc[i] += c[i] * c[3]
                    acc[3] += c[3]
            a = acc[3]
            if a:
                row += bytes([round(acc[0] / a), round(acc[1] / a), round(acc[2] / a), round(a / (ss * ss))])
            else:
                row += b"\0\0\0\0"
        rows.append(bytes(row))
    raw = b"".join(rows)

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")


if __name__ == "__main__":
    out = ROOT / "plugin" / "icons"
    out.mkdir(parents=True, exist_ok=True)
    for size in (64, 128, 256, 512):
        (out / f"icon_{size}.png").write_bytes(render(size))
        print(out / f"icon_{size}.png")
