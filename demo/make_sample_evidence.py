#!/usr/bin/env python3
"""Generate SYNTHETIC demo images for the Phase 2 evidence walkthrough. Pure standard library (no Pillow needed).

These are NOT photographs of waste. Each is a labelled placeholder ("SYNTHETIC DEMO IMAGE") with a different colour,
so every file has a different SHA-256 (identical files are flagged as duplicates by the server, by design).

    python3 demo/make_sample_evidence.py        ->  demo/assets/*.png
"""
import os
import struct
import zlib

# 5x7 bitmap font, only the characters we need
FONT = {
    "0": "01110 10001 10011 10101 11001 10001 01110", "1": "00100 01100 00100 00100 00100 00100 01110", "2": "01110 10001 00001 00010 00100 01000 11111",
    "3": "11110 00001 00001 01110 00001 00001 11110", "4": "00010 00110 01010 10010 11111 00010 00010", "5": "11111 10000 11110 00001 00001 10001 01110",
    "6": "00110 01000 10000 11110 10001 10001 01110", "7": "11111 00001 00010 00100 01000 01000 01000", "8": "01110 10001 10001 01110 10001 10001 01110",
    "9": "01110 10001 10001 01111 00001 00010 01100", "K": "10001 10010 10100 11000 10100 10010 10001", "G": "01110 10001 10000 10111 10001 10001 01110",
    "S": "01111 10000 10000 01110 00001 00001 11110", "Y": "10001 10001 01010 00100 00100 00100 00100", "N": "10001 11001 10101 10011 10001 10001 10001",
    "T": "11111 00100 00100 00100 00100 00100 00100", "H": "10001 10001 10001 11111 10001 10001 10001", "E": "11111 10000 10000 11110 10000 10000 11111",
    "I": "01110 00100 00100 00100 00100 00100 01110", "C": "01110 10001 10000 10000 10000 10001 01110", "D": "11110 10001 10001 10001 10001 10001 11110",
    "M": "10001 11011 10101 10101 10001 10001 10001", "O": "01110 10001 10001 10001 10001 10001 01110", "A": "01110 10001 10001 11111 10001 10001 10001",
    "W": "10001 10001 10001 10101 10101 11011 10001", "R": "11110 10001 10001 11110 10100 10010 10001", "F": "11111 10000 10000 11110 10000 10000 10000",
    "L": "10000 10000 10000 10000 10000 10000 11111", "P": "11110 10001 10001 11110 10000 10000 10000", "U": "10001 10001 10001 10001 10001 10001 01110", "B": "11110 10001 10001 11110 10001 10001 11110",
    " ": "00000 00000 00000 00000 00000 00000 00000", ".": "00000 00000 00000 00000 00000 01100 01100",
}
W, H, SCALE = 480, 270, 5


def png(pixels: bytearray, w: int, h: int) -> bytes:
    raw = b"".join(b"\x00" + bytes(pixels[y * w * 3:(y + 1) * w * 3]) for y in range(h))
    def chunk(t, d): return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")


def draw(text, x, y, buf, scale, color):
    for ch in text:
        rows = FONT[ch].split()
        for r, row in enumerate(rows):
            for c, bit in enumerate(row):
                if bit == "1":
                    for dy in range(scale):
                        for dx in range(scale):
                            px, py = x + c * scale + dx, y + r * scale + dy
                            if 0 <= px < W and 0 <= py < H:
                                i = (py * W + px) * 3
                                buf[i:i + 3] = bytes(color)
        x += 6 * scale


def make(name, bg, headline, sub, fg=(255, 255, 255)):
    buf = bytearray(bytes(bg) * (W * H))
    for band in range(0, H, 18):                       # a diagonal-free banding so each image is visibly distinct
        for x in range(W):
            i = (band * W + x) * 3
            buf[i:i + 3] = bytes(max(0, c - 22) for c in bg)
    draw(headline, 24, 60, buf, SCALE, fg)
    draw(sub, 24, 150, buf, 3, fg)
    draw("SYNTHETIC DEMO IMAGE", 24, 230, buf, 3, (255, 224, 130))
    path = os.path.join(os.path.dirname(__file__), "assets", name)
    open(path, "wb").write(png(buf, W, H))
    print("wrote", path, os.path.getsize(path), "bytes")


if __name__ == "__main__":
    os.makedirs(os.path.join(os.path.dirname(__file__), "assets"), exist_ok=True)
    make("1_worker_load_photo.png", (37, 99, 176), "520 KG", "WORKER LOAD PHOTO")
    make("2_facility_weighbridge_390kg.png", (109, 63, 178), "390 KG", "FACILITY WEIGHBRIDGE")
    make("3_audit1_scale_515kg.png", (217, 112, 15), "515 KG", "AUDIT 1 SCALE")
    make("4_audit2_scale_385kg.png", (30, 132, 73), "385 KG", "AUDIT 2 SCALE")
