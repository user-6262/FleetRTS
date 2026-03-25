"""
Split a 4x4 concept sheet (Faction A left, Faction B right) into 16 transparent PNGs.

Canonical class names come from Faction B labels only (typos fixed); the same name is
used for the matching Faction A cell (same row, column within that half).

Game reference (core/data.json ship_classes):
  Strike: Fighter, Bomber, Interceptor
  Capitals: Frigate, Destroyer, Cruiser, Battleship, Dreadnought, Carrier

This sheet does not include Destroyer, Bomber, or Dreadnought art slots.

Example:
  python tools/split_ship_portrait_sheet.py path/to/sheet.png -o assets/portraits/ships
"""
from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image

# (row 0..3, col 0..1 within each faction half) -> name from Faction B artwork (corrected)
CANONICAL_CLASS_BY_CELL: tuple[tuple[str, str], ...] = (
    ("Fighter", "Interceptor"),
    ("Frigate", "Frigate"),  # sheet typo FRIGAEE -> Frigate
    ("Battleship", "Cruiser"),
    ("Battleship", "Carrier"),
)


def _rgba_key_white_and_labels(im: Image.Image, *, white_floor: int = 248) -> Image.Image:
    """RGB -> RGBA; drop near-white background; drop saturated blue/red (faction captions)."""
    rgb = im.convert("RGB")
    px = rgb.load()
    w, h = rgb.size
    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    opx = out.load()
    for y in range(h):
        for x in range(w):
            r, g, b = px[x, y]
            if r >= white_floor and g >= white_floor and b >= white_floor:
                continue
            # Blue header / Faction A labels (avoid eating cool gray ships: require hue)
            if b > max(r, g) + 35 and b > 110 and r < 120:
                continue
            # Red Faction B labels
            if r > max(g, b) + 45 and r > 130 and g < 110 and b < 110:
                continue
            opx[x, y] = (r, g, b, 255)
    return out


def _trim_alpha(im: Image.Image, pad: int = 2) -> Image.Image:
    bbox = im.getbbox()
    if not bbox:
        return im
    x0, y0, x1, y1 = bbox
    x0 = max(0, x0 - pad)
    y0 = max(0, y0 - pad)
    x1 = min(im.width, x1 + pad)
    y1 = min(im.height, y1 + pad)
    return im.crop((x0, y0, x1, y1))


def split_sheet(
    src: Path,
    out_dir: Path,
    *,
    header_frac: float = 0.065,
    label_frac: float = 0.13,
    rows: int = 4,
    cols: int = 4,
) -> None:
    img = Image.open(src).convert("RGB")
    w, h = img.size
    y0 = int(h * header_frac)
    body = img.crop((0, y0, w, h))
    bw, bh = body.size
    cw = bw // cols
    ch = bh // rows

    out_dir.mkdir(parents=True, exist_ok=True)

    for row in range(rows):
        for col in range(cols):
            x = col * cw
            y = row * ch
            cell = body.crop((x, y, x + cw, y + ch))
            # Strip bottom caption strip inside the cell
            cut = int(ch * label_frac)
            cell = cell.crop((0, 0, cw, ch - cut))

            rgba = _rgba_key_white_and_labels(cell)
            rgba = _trim_alpha(rgba)

            half = cols // 2
            if col < half:
                faction = "faction_a"
                inner_col = col
            else:
                faction = "faction_b"
                inner_col = col - half
            class_name = CANONICAL_CLASS_BY_CELL[row][inner_col]
            fname = f"{faction}_r{row}c{inner_col}_{class_name}.png"
            rgba.save(out_dir / fname, optimize=True)
            print(out_dir / fname)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("sheet", type=Path, help="Source PNG/JPEG sheet")
    ap.add_argument(
        "-o",
        "--out",
        type=Path,
        default=Path("assets/portraits/ships"),
        help="Output directory",
    )
    ap.add_argument("--header-frac", type=float, default=0.065)
    ap.add_argument("--label-frac", type=float, default=0.13)
    args = ap.parse_args()
    if not args.sheet.is_file():
        print("Missing sheet:", args.sheet, flush=True)
        return 1
    split_sheet(
        args.sheet,
        args.out,
        header_frac=args.header_frac,
        label_frac=args.label_frac,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
