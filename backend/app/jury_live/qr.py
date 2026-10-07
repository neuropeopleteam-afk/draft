"""QR-код зала: матрица — кодировщиком reportlab (уже в зависимостях), вывод — SVG и PNG без сторонних библиотек."""
from __future__ import annotations

from functools import lru_cache
from html import escape
import struct
import zlib

from reportlab.graphics.barcode import qrencoder

QUIET = 4  # «тихая зона» по стандарту — 4 модуля


@lru_cache(maxsize=64)
def matrix(text: str) -> tuple[tuple[bool, ...], ...]:
    q = qrencoder.QRCode(None, qrencoder.QRErrorCorrectLevel.M)  # M: до 15 % повреждений (блики на экране)
    q.addData(text)
    q.make()
    n = q.getModuleCount()
    return tuple(tuple(bool(q.isDark(r, c)) for c in range(n)) for r in range(n))


def svg(text: str, *, dark: str = "#20124D", light: str = "#FFFFFF") -> str:
    m = matrix(text)
    n = len(m) + 2 * QUIET
    path = "".join(f"M{c + QUIET} {r + QUIET}h1v1h-1z" for r, row in enumerate(m) for c, v in enumerate(row) if v)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {n} {n}" shape-rendering="crispEdges" '
            f'role="img" aria-label="QR-код: {escape(text, quote=True)}"><rect width="{n}" height="{n}" fill="{light}"/>'
            f'<path fill="{dark}" d="{path}"/></svg>')


def png(text: str, scale: int = 16) -> bytes:
    """Чёрно-белый PNG (1 бит на пиксель): для слайда презентации — крупно и резко при любом масштабе."""
    m = matrix(text)
    n = len(m) + 2 * QUIET
    size = n * scale
    rows = []
    for r in range(n):
        bits = []
        for c in range(n):
            mr, mc = r - QUIET, c - QUIET
            dark = 0 <= mr < len(m) and 0 <= mc < len(m) and m[mr][mc]
            bits.extend([0 if dark else 1] * scale)  # 1 — белый
        line = bytearray()
        for i in range(0, size, 8):
            byte = 0
            for k, b in enumerate(bits[i:i + 8]):
                byte |= b << (7 - k)
            line.append(byte)
        rows.extend([b"\x00" + bytes(line)] * scale)

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", size, size, 1, 0, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(b"".join(rows), 9)) + \
        chunk(b"IEND", b"")
