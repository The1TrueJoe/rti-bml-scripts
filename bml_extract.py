#!/usr/bin/env python3
"""
bml_extract.py  –  Extract images from an RTI .bml bitmap library.

Usage:
    python3 bml_extract.py <file.bml> [output_dir] [--scale N]

Outputs one PNG per record named after the icon's internal label.
Default output directory is  <bml_stem>_extracted/  next to the .bml file.
Default scale is 4 (nearest-neighbour upscale for visibility; use 1 for raw pixels).

Format notes (reverse-engineered):
    File header  : 12 bytes  – magic(4) count_LE16(2) version(2) flags(4)
    Record       : 18 + 23 + pixel_bytes bytes
        [0:2]    marker   0x12 0x21
        [2:4]    width    LE uint16
        [4:6]    height   LE uint16
        [6:14]   fixed    01 00 01 00 01 00 00 09
        [14:18]  unknown  (varies – preserved on extract, zeroed on pack)
        [18..]   name     null-terminated
        [..]     meta     fills the 23-byte name-field:
                          meta[0:3] = fg R,G,B  (if space allows)
                          meta[-2:] = pixel_data_size LE16
        [41..]   pixels   big-endian packed 1-bpp rows
                          bit 1 = bg (white), bit 0 = fg (logo color)
                          row stride = ceil(width / 8) bytes
"""

import argparse
import math
import struct
import sys
from pathlib import Path
from PIL import Image

MAGIC = b'\x27\x75\x37\x09'
MARKER = b'\x12\x21'
FIXED_HDR = 18      # bytes before name
NAME_FIELD = 23     # bytes for name + meta (name\0 + remaining meta)


def row_stride(w: int) -> int:
    return math.ceil(w / 8)


def find_records(data: bytes):
    """Return list of (offset, w, h) for every valid record marker."""
    results = []
    i = 0
    while True:
        pos = data.find(MARKER, i)
        if pos == -1:
            break
        if pos + 6 <= len(data):
            w = struct.unpack_from('<H', data, pos + 2)[0]
            h = struct.unpack_from('<H', data, pos + 4)[0]
            if 1 <= w <= 255 and 1 <= h <= 255:
                results.append((pos, w, h))
        i = pos + 1
    return results


def decode_record(data: bytes, start: int, w: int, h: int):
    """
    Extract name, fg color, and pixel bytes from one record.
    Record layout: FIXED_HDR(18) + NAME_FIELD(23) + pixel_bytes
    """
    pix_bytes = h * row_stride(w)
    rec_len = FIXED_HDR + NAME_FIELD + pix_bytes
    rec = data[start : start + rec_len]
    if len(rec) < rec_len:
        raise ValueError(f"Truncated record at 0x{start:04X}")

    # Name: null-terminated, starts at offset FIXED_HDR
    null_pos = rec.index(b'\x00', FIXED_HDR)
    name_raw = rec[FIXED_HDR:null_pos]
    try:
        name = name_raw.decode('latin-1')
    except Exception:
        name = name_raw.hex()

    # Meta: bytes after name\0 up to pixel data
    meta = rec[null_pos + 1 : FIXED_HDR + NAME_FIELD]

    # fg color from first 3 meta bytes (if available)
    fg = (0, 0, 0)
    if len(meta) >= 3:
        r, g, b = meta[0], meta[1], meta[2]
        if (r, g, b) not in ((0, 0, 0), (255, 255, 255)):
            fg = (r, g, b)

    pix = rec[FIXED_HDR + NAME_FIELD :]
    return name, fg, pix


def render_png(w: int, h: int, pix: bytes, fg: tuple, bg: tuple = (255, 255, 255),
               scale: int = 1) -> Image.Image:
    """Decode 1-bpp pixel data into a PIL Image.  1=bg, 0=fg."""
    stride = row_stride(w)
    img = Image.new('RGB', (w, h))
    pixels = img.load()
    for row in range(h):
        val = int.from_bytes(pix[row * stride : row * stride + stride], 'big')
        shift_base = stride * 8 - 1
        for col in range(w):
            bit = (val >> (shift_base - col)) & 1
            pixels[col, row] = bg if bit else fg
    if scale > 1:
        img = img.resize((w * scale, h * scale), Image.NEAREST)
    return img


def extract(bml_path: Path, out_dir: Path, scale: int = 4):
    data = bml_path.read_bytes()
    if data[:4] != MAGIC:
        sys.exit(f"ERROR: {bml_path.name} is not a .bml file (bad magic)")

    count_hdr = struct.unpack_from('<H', data, 4)[0]
    print(f"{bml_path.name}: {count_hdr} record(s) declared in header")

    # Determine the dominant w,h across all markers (handles mixed sizes)
    all_markers = find_records(data)
    from collections import Counter
    wh_count = Counter((w, h) for _, w, h in all_markers)
    dominant_wh, _ = wh_count.most_common(1)[0]
    dom_w, dom_h = dominant_wh

    # Filter to only the dominant size (eliminates false positives inside pixels)
    true_markers = [(p, w, h) for p, w, h in all_markers if (w, h) == dominant_wh]
    print(f"  Found {len(true_markers)} {dom_w}×{dom_h} record(s)")

    out_dir.mkdir(parents=True, exist_ok=True)
    extracted = 0
    for pos, w, h in true_markers:
        try:
            name, fg, pix = decode_record(data, pos, w, h)
        except (ValueError, IndexError) as e:
            print(f"  SKIP 0x{pos:04X}: {e}")
            continue

        img = render_png(w, h, pix, fg, scale=scale)
        safe = name.replace('/', '_').replace(' ', '_')  # / is the only illegal char on macOS
        out_path = out_dir / f"{safe}.png"
        img.save(out_path)
        print(f"  [{w}×{h}] '{name}'  fg={fg}  → {out_path.name}")
        extracted += 1

    print(f"Extracted {extracted} image(s) to {out_dir}/")


def main():
    ap = argparse.ArgumentParser(description='Extract images from an RTI .bml file')
    ap.add_argument('bml', type=Path, help='.bml input file')
    ap.add_argument('outdir', nargs='?', type=Path, help='Output directory (default: <bml>_extracted/)')
    ap.add_argument('--scale', type=int, default=4, metavar='N',
                    help='Nearest-neighbour upscale factor (default 4; use 1 for raw pixels)')
    args = ap.parse_args()

    bml_path = args.bml.resolve()
    if not bml_path.exists():
        sys.exit(f"ERROR: {bml_path} not found")

    out_dir = args.outdir.resolve() if args.outdir else bml_path.parent / f"{bml_path.stem}_extracted"
    extract(bml_path, out_dir, scale=args.scale)


if __name__ == '__main__':
    main()
