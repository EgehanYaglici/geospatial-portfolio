#!/usr/bin/env python3
"""
Step 16 - Put the finished boundaries back on the source sheets.

This is the check that actually matters. Everything upstream can be
self-consistent and still be wrong: the acceptance checks prove the polygons
tile the territory, but not that they tile it where the atlas says. Drawing
the delivered geometry over the georeferenced plate answers that directly -
the line either follows the printed boundary or it does not, and it is
visible at a glance.

It also measures it. For every sheet, the delivered boundary is sampled and
each sample's distance to the nearest dark pixel of the printed line work is
recorded, giving a distribution rather than an impression.

Output: qa/source_overlay_<page>.jpg, qa/source_overlay.json
"""
import json
import pathlib
import sys

import cv2
import geopandas as gpd
import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from gpkg_io import read_gpkg

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "01_source"
GEO = ROOT / "02_georef"
VEC = ROOT / "03_vector"
QA = ROOT / "qa"

SHEETS = {"22": "Balomotwa", "23": "Banweshi", "24": "Kiona-Ngoy"}
SAMPLE_M = 300.0


def to_pixels(geom, Ai, ti):
    parts = geom.geoms if geom.geom_type.startswith("Multi") else [geom]
    out = []
    for p in parts:
        rings = [p.exterior] + list(p.interiors) if p.geom_type == "Polygon" \
            else [p]
        for r in rings:
            xy = np.asarray(r.coords)
            out.append((xy @ Ai.T + ti))
    return out


def main():
    gcps = json.loads((GEO / "gcps.json").read_text())
    grp = read_gpkg(VEC / "mitwaba.gpkg", "groupements")
    report = {}

    for pg, sector in SHEETS.items():
        img = cv2.imread(str(SRC / f"page-{pg}.png"))
        h, w = img.shape[:2]
        M = np.array(gcps[pg]["affine"])
        A = np.array([[M[0, 0], M[0, 1]], [M[1, 0], M[1, 1]]])
        Ai = np.linalg.inv(A)
        ti = -Ai @ np.array([M[0, 2], M[1, 2]])

        # printed line work: locally dark, thin
        g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        bg = cv2.GaussianBlur(g, (0, 0), 25)
        ink = ((bg.astype(np.int16) - g.astype(np.int16)) > 30).astype(np.uint8)
        dist_px = cv2.distanceTransform(1 - ink, cv2.DIST_L2, 3)

        m_per_px = abs(M[0, 0]) * 111320 * np.cos(np.radians(-9.2))
        sub = grp[grp.sector == sector]
        vis = img.copy()
        dists = []
        for _, r in sub.iterrows():
            for xy in to_pixels(r.geometry, Ai, ti):
                cv2.polylines(vis, [xy.astype(np.int32)], True, (0, 0, 255),
                              5, cv2.LINE_AA)
                n = max(2, int(len(xy)))
                for x, y in xy[:: max(1, int(SAMPLE_M / m_per_px))]:
                    xi, yi = int(round(x)), int(round(y))
                    if 0 <= xi < w and 0 <= yi < h:
                        dists.append(dist_px[yi, xi] * m_per_px)

        d = np.asarray(dists)
        stats = dict(sector=sector, samples=int(d.size),
                     median_m=round(float(np.median(d)), 1),
                     p90_m=round(float(np.percentile(d, 90)), 1),
                     within_250m=round(float((d < 250).mean() * 100), 1),
                     within_500m=round(float((d < 500).mean() * 100), 1))
        report[f"page-{pg}"] = stats

        cv2.putText(vis, f"page-{pg}  {sector}  -  delivered boundary in red",
                    (30, 60), cv2.FONT_HERSHEY_SIMPLEX, 1.4, (0, 0, 0), 8,
                    cv2.LINE_AA)
        cv2.putText(vis, f"page-{pg}  {sector}  -  delivered boundary in red",
                    (30, 60), cv2.FONT_HERSHEY_SIMPLEX, 1.4, (255, 255, 255), 3,
                    cv2.LINE_AA)
        s = 1600 / max(h, w)
        cv2.imwrite(str(QA / f"source_overlay_{pg}.jpg"),
                    cv2.resize(vis, None, fx=s, fy=s),
                    [cv2.IMWRITE_JPEG_QUALITY, 88])
        print(f"page-{pg} {sector:<12} median {stats['median_m']:6.1f} m  "
              f"p90 {stats['p90_m']:7.1f} m  "
              f"within 250 m: {stats['within_250m']:5.1f}%  "
              f"within 500 m: {stats['within_500m']:5.1f}%")

    (QA / "source_overlay.json").write_text(json.dumps(report, indent=2))
    print("\nwrote qa/source_overlay_*.jpg")


if __name__ == "__main__":
    main()
