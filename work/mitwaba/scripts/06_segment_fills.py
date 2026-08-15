#!/usr/bin/env python3
"""
Step 6 - Segment the groupement fills on each sector sheet.

Each sheet colours every groupement of its sector with its own flat tint, so
the boundaries are recoverable from colour rather than by tracing lines. The
work is in everything that sits ON TOP of those tints: roads, rivers, village
dots, place names, the inscription-centre callout boxes, park hatching, and
the legend / statistics / locator / enlargement boxes.

The method is deliberately built so the result is topologically clean by
construction:

  1. mask the map interior (inside the neatline, minus the printed boxes),
  2. cluster the interior colours and split them into "fill" tints and
     "not fill" (paper, grey neighbours, ink, roads, water),
  3. every interior pixel that is a fill tint keeps its class; everything else
     inside the sector is left UNKNOWN,
  4. fill the unknowns by nearest labelled pixel.

Because step 4 assigns each pixel exactly one class, polygonising the result
cannot produce a gap or an overlap between neighbouring groupements - which is
the failure mode of vectorising each colour separately and stitching after.

Output: 03_vector/labels_<page>.npy, qa/seg_<page>.jpg, qa/regions_<page>.jpg
"""
import json
import pathlib

import cv2
import numpy as np
from scipy import ndimage as ndi

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "01_source"
GEO = ROOT / "02_georef"
VEC = ROOT / "03_vector"
QA = ROOT / "qa"
VEC.mkdir(exist_ok=True)

SHEETS = ["22", "23", "24"]      # the three sector sheets carry the boundaries
K = 16                            # colour clusters
MIN_REGION_PX = 4000              # drop specks smaller than this


def interior_mask(shape, corners, shrink=8):
    h, w = shape
    pts = np.array([corners[k] for k in ("tl", "tr", "br", "bl")], np.float32)
    c = pts.mean(axis=0)
    pts = (c + (pts - c) * (1 - shrink / 1000.0)).astype(np.int32)
    m = np.zeros((h, w), np.uint8)
    cv2.fillPoly(m, [pts], 1)
    return m


def find_boxes(gray, inside):
    """
    Locate the printed rectangles inside the map: legend, statistics, locator
    map and the enlargement insets. They all have a thin dark border and a
    pale fill, and they hide whatever is underneath, so they must be cut out
    before any colour is trusted.
    """
    fg = cv2.GaussianBlur(gray, (0, 0), 2)
    bg = cv2.GaussianBlur(gray, (0, 0), 61)
    ink = (((bg.astype(np.int16) - fg.astype(np.int16)) > 20) & (inside > 0)).astype(np.uint8)
    h, w = gray.shape
    hk = cv2.getStructuringElement(cv2.MORPH_RECT, (int(w * 0.045), 1))
    vk = cv2.getStructuringElement(cv2.MORPH_RECT, (1, int(h * 0.045)))
    lines = cv2.dilate(cv2.morphologyEx(ink, cv2.MORPH_OPEN, hk), np.ones((3, 3), np.uint8)) | \
            cv2.dilate(cv2.morphologyEx(ink, cv2.MORPH_OPEN, vk), np.ones((3, 3), np.uint8))
    closed = cv2.morphologyEx(lines, cv2.MORPH_CLOSE,
                              cv2.getStructuringElement(cv2.MORPH_RECT, (25, 25)))
    n, lab, stats, _ = cv2.connectedComponentsWithStats(closed, 8)
    boxes = []
    for i in range(1, n):
        x, y, bw, bh, area = stats[i]
        if bw < w * 0.06 or bh < h * 0.04:
            continue
        if bw * bh > 0.45 * w * h:
            continue
        # a real box is close to a filled rectangle once its outline is closed
        filled = ndi.binary_fill_holes(lab[y:y + bh, x:x + bw] == i)
        if filled.sum() < 0.55 * bw * bh:
            continue
        boxes.append((int(x), int(y), int(bw), int(bh)))
    return boxes


def main():
    frames = json.loads((GEO / "frames.json").read_text())
    summary = {}

    for pg in SHEETS:
        img = cv2.imread(str(SRC / f"page-{pg}.png"))
        h, w = img.shape[:2]
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        inside = interior_mask((h, w), frames[pg]["corners"])

        boxes = find_boxes(gray, inside)
        work = inside.copy()
        for x, y, bw, bh in boxes:
            work[max(0, y - 4):y + bh + 4, max(0, x - 4):x + bw + 4] = 0
        print(f"page-{pg}: {len(boxes)} printed boxes masked out, "
              f"{work.sum()/1e6:.2f} Mpx of map left")

        vis = img.copy()
        for x, y, bw, bh in boxes:
            cv2.rectangle(vis, (x, y), (x + bw, y + bh), (0, 0, 255), 6)
        cv2.polylines(vis, [np.array([frames[pg]["corners"][k] for k in
                                      ("tl", "tr", "br", "bl")], np.int32)],
                      True, (0, 200, 0), 5)
        s = 1500 / max(h, w)
        cv2.imwrite(str(QA / f"boxes_{pg}.jpg"), cv2.resize(vis, None, fx=s, fy=s),
                    [cv2.IMWRITE_JPEG_QUALITY, 85])
        summary[pg] = dict(boxes=boxes)

    (VEC / "boxes.json").write_text(json.dumps(summary, indent=2))
    print("\nwrote", VEC / "boxes.json")


if __name__ == "__main__":
    main()
