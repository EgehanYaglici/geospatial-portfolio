#!/usr/bin/env python3
"""
Step 2a - Dump the rectified margin strips of every sheet as flat images.

Purpose: let a human (or the operator) read the graticule labels directly and
confirm the coordinate sequence, instead of trusting OCR on 8-pt text
photographed through a book. The strips are rotated so the neatline is exactly
axis-aligned and are written at 2x, side labels turned upright.

Output: qa/bands/<page>_<side>.png
"""
import json
import pathlib

import cv2
import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "01_source"
OUT = ROOT / "02_georef"
BANDS = ROOT / "qa" / "bands"
BANDS.mkdir(parents=True, exist_ok=True)

PAGES = ["21", "22", "23", "24"]
NEAR, FAR = 4, 112


def rectify(img, edge, side):
    h, w = img.shape[:2]
    a, b = edge["a"], edge["b"]
    ang = np.degrees(np.arctan(a))
    if side in ("top", "bottom"):
        c = (w / 2.0, a * (w / 2.0) + b)
        M = cv2.getRotationMatrix2D(c, ang, 1.0)
    else:
        c = (a * (h / 2.0) + b, h / 2.0)
        M = cv2.getRotationMatrix2D(c, -ang, 1.0)
    warp = cv2.warpAffine(img, M, (w, h), flags=cv2.INTER_CUBIC,
                          borderValue=(255, 255, 255))
    if side == "top":
        return warp[max(0, int(c[1]) - FAR):int(c[1]) - NEAR, :]
    if side == "bottom":
        return warp[int(c[1]) + NEAR:min(h, int(c[1]) + FAR), :]
    if side == "left":
        strip = warp[:, max(0, int(c[0]) - FAR):int(c[0]) - NEAR]
        return cv2.rotate(strip, cv2.ROTATE_90_CLOCKWISE)
    strip = warp[:, int(c[0]) + NEAR:min(w, int(c[0]) + FAR)]
    return cv2.rotate(strip, cv2.ROTATE_90_CLOCKWISE)


def main():
    frames = json.loads((OUT / "frames.json").read_text())
    for pg in PAGES:
        img = cv2.imread(str(SRC / f"page-{pg}.png"), cv2.IMREAD_COLOR)
        for side in ("top", "bottom", "left", "right"):
            band = rectify(img, frames[pg]["edges"][side], side)
            band = cv2.resize(band, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
            cv2.imwrite(str(BANDS / f"{pg}_{side}.png"), band)
            print(f"{pg} {side}: {band.shape[1]}x{band.shape[0]}")


if __name__ == "__main__":
    main()
