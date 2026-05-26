#!/usr/bin/env python3
"""
img_to_bml_png.py  –  Scale any image to 26×26 (or WxH) and convert to
                       binary black/white PNG ready for bml_pack.py.

Usage:
    python3 img_to_bml_png.py <input_image> [output.png]
                              [--width 26] [--height 26]
                              [--threshold 128]
                              [--preview]

Options:
    --width / --height : target icon dimensions (default 26×26)
    --threshold N      : greyscale cutoff 0-255; pixels darker than N become
                         foreground (black/logo-color), brighter become bg (white).
                         Default 128.  Try lower (e.g. 80) for light logos,
                         higher (e.g. 180) for faint/thin strokes.
    --preview          : also save a 8× upscaled preview PNG alongside output

The script:
    1. Opens the source image (any format Pillow supports, incl. .webp).
    2. Flattens transparency onto a white background.
    3. Converts to greyscale.
    4. Downscales to target size using LANCZOS (best quality).
    5. Applies threshold → pure black (0,0,0) / white (255,255,255).
    6. Writes output PNG.

Output PNG can be fed directly to bml_pack.py; the fg color will be detected
as black (0,0,0).  If you want a colored icon (e.g. Control4 red), pass the
--fg option to bml_pack.py or rename the file with the __FG_R_G_B suffix.
"""

import argparse
import sys
from pathlib import Path
from PIL import Image, ImageFilter


def img_to_bw(src: Path, out: Path, w: int, h: int,
              threshold: int, preview: bool):
    img = Image.open(src)

    # Flatten any transparency onto white
    if img.mode in ('RGBA', 'LA') or (img.mode == 'P' and 'transparency' in img.info):
        bg = Image.new('RGB', img.size, (255, 255, 255))
        if img.mode != 'RGBA':
            img = img.convert('RGBA')
        bg.paste(img, mask=img.split()[3])
        img = bg
    else:
        img = img.convert('RGB')

    # Greyscale
    grey = img.convert('L')

    # Apply a slight Gaussian blur before thresholding – reduces aliasing artifacts
    # when downscaling logos with thin strokes.
    grey = grey.filter(ImageFilter.GaussianBlur(radius=0.5))

    # Downscale
    small = grey.resize((w, h), Image.LANCZOS)

    # Threshold: below → black (fg), at/above → white (bg)
    bw = small.point(lambda p: 0 if p < threshold else 255, '1')
    bw_rgb = bw.convert('RGB')

    bw_rgb.save(out)
    print(f"Saved {w}×{h} B&W PNG → {out}")

    # Count fg pixels for sanity
    fg_count = sum(1 for px in bw_rgb.getdata() if px == (0, 0, 0))
    total = w * h
    print(f"  {fg_count}/{total} fg pixels ({100*fg_count//total}% coverage)")

    if preview:
        scale = 8
        prev_path = out.parent / (out.stem + '_preview.png')
        bw_rgb.resize((w * scale, h * scale), Image.NEAREST).save(prev_path)
        print(f"  Preview (8×) → {prev_path}")

    return bw_rgb


def main():
    ap = argparse.ArgumentParser(
        description='Convert any image to a binary B&W PNG sized for .bml icons')
    ap.add_argument('src',  type=Path, help='Input image (jpg/png/webp/etc.)')
    ap.add_argument('dst',  nargs='?', type=Path,
                    help='Output PNG path (default: <src_stem>_26x26.png)')
    ap.add_argument('--width',     type=int, default=26, metavar='W')
    ap.add_argument('--height',    type=int, default=26, metavar='H')
    ap.add_argument('--threshold', type=int, default=128, metavar='N',
                    help='Greyscale threshold 0-255 (default 128; lower = less fg)')
    ap.add_argument('--preview',   action='store_true',
                    help='Also write an 8× upscaled preview PNG')
    args = ap.parse_args()

    src = args.src.resolve()
    if not src.exists():
        sys.exit(f"ERROR: {src} not found")

    dst = args.dst.resolve() if args.dst else \
          src.parent / f"{src.stem}_{args.width}x{args.height}.png"

    img_to_bw(src, dst, args.width, args.height, args.threshold, args.preview)


if __name__ == '__main__':
    main()
