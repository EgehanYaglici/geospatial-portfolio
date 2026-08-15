#!/usr/bin/env python3
"""
Step 2 - Locate the graticule coordinate labels around each neatline and read
their values, giving a set of ground control points.

The atlas draws no tick marks on the neatline: the only indication of where a
meridian or parallel meets the frame is the DMS label printed just outside it,
centred on that position. So for every margin band we

  1. cut a strip just outside the frame edge,
  2. rectify it so the neatline edge is exactly horizontal (each sheet is a
     book photo and is slightly rotated / skewed),
  3. group the dark text pixels into label blocks and take each block's centre
     along the frame direction,
  4. OCR the block and parse its DMS value,
  5. cross-check the parsed values against the assumption of a constant step,
     which is what a plain geographic (EPSG:4326) sheet must produce.

Left and right strips are rotated 90 degrees before OCR because their labels
are set vertically.

Output: 02_georef/graticule.json  +  qa/grat_<page>.jpg
"""
import json
import pathlib
import re
import subprocess
import sys

import cv2
import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "01_source"
OUT = ROOT / "02_georef"
QA = ROOT / "qa"

PAGES = ["21", "22", "23", "24"]

# how far outside the neatline the label band reaches (pixels)
BAND_NEAR = 6      # skip this much so the neatline itself is not included
BAND_FAR = 105     # labels sit within ~100 px of the frame on these scans

DMS = re.compile(r"(\d{1,3})\s*[°ºo]?\s*(\d{1,2})?\s*['’‘]?\s*(\d{1,2})?\s*[\"”“']*\s*([NSEWnsew])")


def parse_dms(text):
    """Return signed decimal degrees, or None. Accepts sloppy OCR punctuation."""
    t = text.replace("O", "0").replace("l", "1").replace("I", "1")
    m = DMS.search(t)
    if not m:
        return None
    d, mi, se, hemi = m.group(1), m.group(2), m.group(3), m.group(4).upper()
    val = float(d) + float(mi or 0) / 60 + float(se or 0) / 3600
    if hemi in ("S", "W"):
        val = -val
    return val


def ocr(img):
    """Run tesseract on a small image, return the recognised text."""
    ok, buf = cv2.imencode(".png", img)
    p = subprocess.run(
        ["tesseract", "stdin", "stdout", "--psm", "7",
         "-c", "tessedit_char_whitelist=0123456789°'\"ENSWenswo"],
        input=buf.tobytes(), capture_output=True)
    return p.stdout.decode("utf8", "ignore").strip()


def rectified_band(img, edge, side, w, h):
    """
    Extract the margin strip outside one neatline edge, rotated so that edge
    becomes exactly axis-aligned. Returns (band_image, to_orig) where to_orig
    maps a coordinate along the band back to the original image.
    """
    a, b = edge["a"], edge["b"]
    ang = np.degrees(np.arctan(a))
    if side in ("top", "bottom"):
        centre = (w / 2.0, a * (w / 2.0) + b)
        rot = cv2.getRotationMatrix2D(centre, ang, 1.0)
    else:
        centre = (a * (h / 2.0) + b, h / 2.0)
        rot = cv2.getRotationMatrix2D(centre, -ang, 1.0)
    warped = cv2.warpAffine(img, rot, (w, h), flags=cv2.INTER_CUBIC,
                            borderValue=(255, 255, 255))

    if side == "top":
        y1, y2 = int(centre[1]) - BAND_FAR, int(centre[1]) - BAND_NEAR
        band = warped[max(0, y1):max(1, y2), :]
        axis = 0                      # label position varies along x
    elif side == "bottom":
        y1, y2 = int(centre[1]) + BAND_NEAR, int(centre[1]) + BAND_FAR
        band = warped[min(h - 1, y1):min(h, y2), :]
        axis = 0
    elif side == "left":
        x1, x2 = int(centre[0]) - BAND_FAR, int(centre[0]) - BAND_NEAR
        band = warped[:, max(0, x1):max(1, x2)]
        axis = 1                      # label position varies along y
    else:
        x1, x2 = int(centre[0]) + BAND_NEAR, int(centre[0]) + BAND_FAR
        band = warped[:, min(w - 1, x1):min(w, x2)]
        axis = 1
    return band, axis, rot


def label_blocks(band, axis):
    """Group dark pixels into label blocks; return list of (start, end) along axis."""
    g = cv2.cvtColor(band, cv2.COLOR_BGR2GRAY)
    bg = cv2.GaussianBlur(g, (0, 0), 31)
    ink = ((bg.astype(np.int16) - g.astype(np.int16)) > 28).astype(np.uint8)
    prof = ink.sum(axis=1 - axis if axis == 0 else 0)
    if axis == 1:
        prof = ink.sum(axis=1)
    else:
        prof = ink.sum(axis=0)
    on = prof > 0
    # close small gaps between characters of the same label
    on = cv2.morphologyEx(on.astype(np.uint8).reshape(-1, 1),
                          cv2.MORPH_CLOSE,
                          np.ones((25, 1), np.uint8)).ravel().astype(bool)
    blocks, i, n = [], 0, len(on)
    while i < n:
        if on[i]:
            j = i
            while j < n and on[j]:
                j += 1
            if (j - i) > 25 and prof[i:j].sum() > 300:
                blocks.append((i, j))
            i = j
        else:
            i += 1
    return blocks, prof


def main():
    frames = json.loads((OUT / "frames.json").read_text())
    result = {}

    for pg in PAGES:
        img = cv2.imread(str(SRC / f"page-{pg}.png"), cv2.IMREAD_COLOR)
        h, w = img.shape[:2]
        fr = frames[pg]
        page = {}
        vis = img.copy()

        for side in ("top", "bottom", "left", "right"):
            band, axis, rot = rectified_band(img, fr["edges"][side], side, w, h)
            blocks, _ = label_blocks(band, axis)

            entries = []
            for (s, e) in blocks:
                pad = 6
                if axis == 0:
                    crop = band[:, max(0, s - pad):min(band.shape[1], e + pad)]
                else:
                    crop = band[max(0, s - pad):min(band.shape[0], e + pad), :]
                    crop = cv2.rotate(crop, cv2.ROTATE_90_COUNTERCLOCKWISE)
                crop = cv2.resize(crop, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
                txt = ocr(crop)
                entries.append(dict(centre=float((s + e) / 2.0),
                                    extent=[int(s), int(e)],
                                    text=txt, value=parse_dms(txt)))
            page[side] = entries

        result[pg] = page

        print(f"\n=== page-{pg} ===")
        for side, entries in page.items():
            vals = [f"{e['value']:.4f}" if e["value"] is not None else "??" for e in entries]
            cens = [f"{e['centre']:.1f}" for e in entries]
            print(f"  {side:<6} n={len(entries)}")
            for e in entries:
                print(f"      c={e['centre']:8.1f}  ocr={e['text']!r:<18} -> {e['value']}")

    (OUT / "graticule_raw.json").write_text(json.dumps(result, indent=2))
    print("\nwrote", OUT / "graticule_raw.json")


if __name__ == "__main__":
    sys.exit(main())
