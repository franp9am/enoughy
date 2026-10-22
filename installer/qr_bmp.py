"""The QR code of a text as a black-and-white BMP, the one image format the
setup wizard shows. The bundled Python runs this at the end of an install
without a server, for the page that carries the address of the codes page:
    python qr_bmp.py <file with the text> <out.bmp>
qrcodegen.py next to it is Project Nayuki's encoder, vendored as it is."""

import struct
import sys
from pathlib import Path

import qrcodegen

SCALE = 4  # pixels per module; a phone reads this from a screen at arm's length
BORDER = 3  # modules of white around the code, the quiet zone

text = Path(sys.argv[1]).read_text(encoding="utf-8").strip()
qr = qrcodegen.QrCode.encode_text(text, qrcodegen.QrCode.Ecc.LOW)
size = (qr.get_size() + 2 * BORDER) * SCALE
row_length = (size * 3 + 3) // 4 * 4  # 24-bit pixels, each row padded to four bytes
rows = []
for y in range(size):
    row = bytearray()
    for x in range(size):
        dark = qr.get_module(x // SCALE - BORDER, y // SCALE - BORDER)  # False outside the code
        row += b"\0\0\0" if dark else b"\xff\xff\xff"
    rows.append(bytes(row).ljust(row_length, b"\0"))
pixels = b"".join(reversed(rows))  # BMP rows go bottom-up
header = struct.pack("<2sIHHI", b"BM", 54 + len(pixels), 0, 0, 54)
info = struct.pack("<IiiHHIIiiII", 40, size, size, 1, 24, 0, len(pixels), 2835, 2835, 0, 0)
Path(sys.argv[2]).write_bytes(header + info + pixels)
