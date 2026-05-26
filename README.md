# RTI BML Tools

Python scripts for working with RTI control system `.bml` bitmap library files.
Reverse-engineered from `Channels.bml` and `Custom.bml` (circa 2006 RTI firmware).

## Scripts

### `bml_extract.py` — Extract images from a `.bml`

```bash
python3 bml_extract.py <file.bml> [output_dir/] [--scale N]
```

Extracts every icon into a PNG named after its internal label.

| Argument | Default | Description |
|---|---|---|
| `output_dir` | `<bml_stem>_extracted/` | Where to write PNGs |
| `--scale N` | `4` | Nearest-neighbour upscale (use `1` for raw pixels) |

**Example:**
```bash
python3 bml_extract.py Channels.bml channels_out/ --scale 8
```

---

### `bml_pack.py` — Pack PNGs into a `.bml`

```bash
python3 bml_pack.py <input_dir/> <output.bml> [--width W] [--height H]
```

Packs every PNG in the directory into a single `.bml` file.

| Argument | Default | Description |
|---|---|---|
| `--width` | `26` | Target icon width in pixels |
| `--height` | `26` | Target icon height in pixels |

- The icon **name** comes from the filename (underscores → spaces, e.g. `ESPN_2.png` → `"ESPN 2"`).
- The **fg color** is auto-detected as the most common non-white pixel.
- Override fg color by appending `__FG_R_G_B` to the filename stem:
  `MyIcon__FG_204_0_0.png` → fg = (204, 0, 0)
- Images must be **exactly** the target size and **pure black-and-white** (use `img_to_bml_png.py` to prepare them).

**Example:**
```bash
python3 bml_pack.py my_icons/ Custom.bml --width 26 --height 26
```

---

### `img_to_bml_png.py` — Convert any photo/logo to a binary icon PNG

```bash
python3 img_to_bml_png.py <input_image> [output.png] [--width 26] [--height 26] [--threshold N] [--preview]
```

Scales any image (JPG, PNG, WEBP, etc.) down to 26×26 and converts it to a
pure black-and-white PNG ready for `bml_pack.py`.

| Argument | Default | Description |
|---|---|---|
| `--width / --height` | `26` | Target size |
| `--threshold N` | `128` | Greyscale cutoff (0–255). Lower = fewer fg pixels. Try `180–200` for clean logos on white backgrounds. |
| `--preview` | off | Also saves an 8× upscaled `_preview.png` for easy eyeballing |

**Example:**
```bash
python3 img_to_bml_png.py my-logo.webp MyIcon.png --threshold 200 --preview
```

---

## Workflow: Add a custom icon

```bash
# 1. Convert your logo to a 26x26 B&W PNG
python3 img_to_bml_png.py mylogo.png MyChannel.png --threshold 180 --preview

# 2. Put it in a folder with any other icons you want to pack
mkdir my_icons/
cp MyChannel.png my_icons/

# 3. Pack into a .bml
python3 bml_pack.py my_icons/ Custom.bml

# 4. Load Custom.bml onto your RTI controller
```

---

## File Format (reverse-engineered)

```
File header  (12 bytes)
  [0:4]   magic     27 75 37 09
  [4:6]   count     LE uint16  (number of records)
  [6:8]   version   01 00
  [8:12]  flags     00 00 00 00

Record  (18 + 23 + pixel_bytes)
  [0:2]   marker    12 21
  [2:4]   width     LE uint16
  [4:6]   height    LE uint16
  [6:14]  fixed     01 00 01 00 01 00 00 09
  [14:18] unknown   (zeroed by packer)
  [18..]  name      null-terminated string (max 20 chars)
  [..]    meta      fills rest of 23-byte name-field:
                      meta[0:3]  = fg R, G, B
                      meta[-2:]  = pixel_data_size LE uint16
  [41..]  pixels    1-bpp big-endian packed rows
                      1 = background (white)
                      0 = foreground (logo color)
                      row stride = ceil(width / 8) bytes
```
