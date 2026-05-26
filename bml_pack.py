#!/usr/bin/env python3
"""
bml_pack.py  –  Pack PNG images into an RTI .bml bitmap library.

Usage:
    python3 bml_pack.py <input_dir> <output.bml> [--width W] [--height H]

All PNGs in input_dir are packed into a single .bml file.

Image requirements:
    - Must be exactly W×H pixels (default 26×26). Use img_to_bml_png.py to prepare images.
    - Must be pure black-and-white (only #000000 and #ffffff pixels).
    - The fg color is the most-common non-white pixel (always black for B&W icons).
    - Override fg color via filename suffix: MyIcon__FG_255_0_0.png → fg (255,0,0).

Format notes (reverse-engineered):
    File header  : magic(4) count_LE16(2) 01 00 00 00 00 00
    Record       : 18-byte header + 23-byte name-field + pixel_bytes
        header   : 12 21  w_LE16  h_LE16  01 00 01 00 01 00 00 09  00 00 00 00
        name-fld : name bytes  00  [meta fills rest of 23 bytes]
        meta     : meta[0:3]=fg R,G,B  meta[3:-2]=zeros  meta[-2:]=pix_size_LE16
        pixels   : big-endian packed 1-bpp rows
                   1=bg (white)  0=fg (logo color)
                   stride = ceil(W/8) bytes

Name limit: 20 characters max (need at least 2 bytes of meta for pix-size field;
            fg color requires at least 5 meta bytes, so names ≤ 17 chars get color).
"""

import argparse
import math
import re
import struct
import sys
from pathlib import Path
from typing import Optional
from PIL import Image

MAGIC        = b'\x27\x75\x37\x09'
MARKER       = b'\x12\x21'
FIXED_FIELDS = b'\x01\x00\x01\x00\x01\x00\x00\x09'  # bytes [6:14]
FIXED_HDR    = 18
NAME_FIELD   = 23


def row_stride(w: int) -> int:
    return math.ceil(w / 8)


BW_PIXELS = {(0, 0, 0), (255, 255, 255)}


def dominant_fg(img: Image.Image, bg: tuple = (255, 255, 255)) -> tuple:
    """Return the most-common non-white pixel color."""
    from collections import Counter
    counts = Counter(img.convert('RGB').getdata())
    counts.pop(bg, None)
    if not counts:
        return (0, 0, 0)
    return counts.most_common(1)[0][0]


def validate_image(img: Image.Image, target_w: int, target_h: int, name: str) -> Optional[str]:
    """Return an error string if the image fails validation, else None."""
    w, h = img.size
    if (w, h) != (target_w, target_h):
        return (f"size {w}×{h} ≠ required {target_w}×{target_h} — "
                f"run img_to_bml_png.py first")
    non_bw = {px for px in img.convert('RGB').getdata() if px not in BW_PIXELS}
    if non_bw:
        sample = ', '.join(str(p) for p in list(non_bw)[:3])
        return (f"contains {len(non_bw)} non-B&W color(s): {sample}… — "
                f"run img_to_bml_png.py to convert to pure black/white")
    return None


def encode_pixels(img: Image.Image, w: int, h: int, fg: tuple,
                  bg: tuple = (255, 255, 255), threshold: int = 128) -> bytes:
    """
    Convert a W×H RGB image to 1-bpp big-endian packed rows.
    Pixels closer to fg → 0 (foreground bit); closer to bg → 1 (background bit).
    For multi-color images a simple luminance threshold is used.
    """
    rgb = img.convert('RGB').resize((w, h), Image.LANCZOS)
    stride = row_stride(w)
    result = bytearray()

    for row in range(h):
        row_bits = 0
        for col in range(w):
            px = rgb.getpixel((col, row))
            # Luminance distance to bg vs fg – bg pixel → bit 1, fg pixel → bit 0
            dist_bg = sum((a - b) ** 2 for a, b in zip(px, bg))
            dist_fg = sum((a - b) ** 2 for a, b in zip(px, fg))
            bit = 1 if dist_bg <= dist_fg else 0
            row_bits = (row_bits << 1) | bit
        # Shift bits to MSB position; unused low bits stay 0 (matches original format)
        row_bits <<= (stride * 8 - w)
        result += row_bits.to_bytes(stride, 'big')

    return bytes(result)


def build_record(name: str, fg: tuple, pix: bytes, w: int, h: int) -> bytes:
    pix_bytes = len(pix)
    if len(name) > 20:
        raise ValueError(f"Name '{name}' is {len(name)} chars; max is 20")

    name_enc = name.encode('latin-1')
    meta_len = NAME_FIELD - len(name_enc) - 1   # bytes after name\0

    if meta_len < 2:
        raise ValueError(f"Name '{name}' is too long (max 20 chars to fit pix-size field)")

    # Build meta: fg color (if room), zeros filler, pix_size LE16 at end
    meta = bytearray(meta_len)
    struct.pack_into('<H', meta, meta_len - 2, pix_bytes)  # last 2 bytes = pix size
    if meta_len >= 3:
        meta[0], meta[1], meta[2] = fg[0], fg[1], fg[2]

    # Fixed 18-byte header: MARKER w h FIXED_FIELDS 4×zero
    hdr = MARKER + struct.pack('<HH', w, h) + FIXED_FIELDS + b'\x00\x00\x00\x00'

    return hdr + name_enc + b'\x00' + bytes(meta) + pix


def parse_fg_from_filename(stem: str):
    """
    If filename contains __FG_R_G_B (e.g. MyIcon__FG_255_0_128.png),
    return (clean_stem, (R, G, B)).  Otherwise return (stem, None).
    """
    m = re.search(r'__FG_(\d+)_(\d+)_(\d+)$', stem)
    if m:
        r, g, b = int(m.group(1)), int(m.group(2)), int(m.group(3))
        clean = stem[:m.start()]
        return clean, (r, g, b)
    return stem, None


def pack(in_dir: Path, out_bml: Path, target_w: int, target_h: int):
    pngs = sorted(in_dir.glob('*.png'))
    if not pngs:
        sys.exit(f"ERROR: no PNG files found in {in_dir}/")

    records = []
    skipped = 0

    for png_path in pngs:
        stem = png_path.stem
        name, override_fg = parse_fg_from_filename(stem)
        # Undo the extractor's safe-name transform: spaces were stored as _
        # (apostrophes and ! are preserved directly in filenames on macOS)
        name = name.replace('_', ' ').strip()
        if not name:
            name = stem

        try:
            img = Image.open(png_path).convert('RGB')
        except Exception as e:
            print(f"  SKIP {png_path.name}: could not open – {e}")
            skipped += 1
            continue

        err = validate_image(img, target_w, target_h, name)
        if err:
            print(f"  SKIP {png_path.name}: {err}")
            skipped += 1
            continue

        fg = override_fg if override_fg else dominant_fg(img)
        pix = encode_pixels(img, target_w, target_h, fg)

        try:
            rec = build_record(name, fg, pix, target_w, target_h)
        except ValueError as e:
            print(f"  SKIP {png_path.name}: {e}")
            skipped += 1
            continue

        records.append((name, fg, rec))
        print(f"  [{target_w}×{target_h}] '{name}'  fg={fg}  ({len(rec)} bytes)")

    if not records:
        sys.exit("ERROR: no valid images to pack")

    # File header: magic + count + 01 00 + 00 00 00 00
    count = len(records)
    file_header = MAGIC + struct.pack('<H', count) + b'\x01\x00' + b'\x00\x00\x00\x00'
    payload = b''.join(r for _, _, r in records)

    out_bml.write_bytes(file_header + payload)
    total = len(file_header + payload)
    skip_note = f"  [{skipped} skipped — fix with img_to_bml_png.py]" if skipped else ''
    print(f"\nWrote {count} record(s) to {out_bml}  ({total} bytes){skip_note}")


def main():
    ap = argparse.ArgumentParser(description='Pack PNG images into an RTI .bml file')
    ap.add_argument('indir',   type=Path, help='Directory of PNG files to pack')
    ap.add_argument('outbml',  type=Path, help='Output .bml file path')
    ap.add_argument('--width',  type=int, default=26, help='Target icon width  (default 26)')
    ap.add_argument('--height', type=int, default=26, help='Target icon height (default 26)')
    args = ap.parse_args()

    in_dir = args.indir.resolve()
    if not in_dir.is_dir():
        sys.exit(f"ERROR: {in_dir} is not a directory")

    pack(in_dir, args.outbml.resolve(), args.width, args.height)


if __name__ == '__main__':
    main()
