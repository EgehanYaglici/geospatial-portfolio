#!/usr/bin/env python3
"""
Step 5 - Independent check on the georeferencing.

The residuals reported in step 3 only say how well the fit reproduces the
labels it was fitted to. They cannot catch a systematic error - a mis-read
label value, or a lattice that slid by one node would fit its own (wrong)
control points perfectly.

So this draws present-day OSM hydrography and main roads straight onto each
georeferenced sheet. Rivers and lakes have not moved since 2016, and the atlas
draws them too, so the two should coincide. Where they do, the sheet is placed
correctly in the world - independently of anything the fit was told.

Output: qa/verify_<page>.jpg
"""
import json
import pathlib

import cv2
import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "01_source"
GEO = ROOT / "02_georef"
CTX = ROOT / "04_context"
QA = ROOT / "qa"

SCALE = 0.5     # render at half the page resolution


def inverse(M):
    A = np.array([[M[0][0], M[0][1]], [M[1][0], M[1][1]]])
    t = np.array([M[0][2], M[1][2]])
    Ai = np.linalg.inv(A)
    return Ai, -Ai @ t


def load_osm(path):
    d = json.loads(pathlib.Path(path).read_text())
    rivers, water, roads, places = [], [], [], []
    for e in d["elements"]:
        t = e.get("tags", {})
        if e["type"] == "node":
            if t.get("place") in ("city", "town", "village"):
                places.append((e["lon"], e["lat"], t.get("name", "")))
            continue
        geoms = []
        if "geometry" in e:
            geoms = [[(p["lon"], p["lat"]) for p in e["geometry"]]]
        elif e["type"] == "relation":
            for m in e.get("members", []):
                if "geometry" in m:
                    geoms.append([(p["lon"], p["lat"]) for p in m["geometry"]])
        for g in geoms:
            if len(g) < 2:
                continue
            if t.get("waterway") == "river":
                rivers.append(g)
            elif t.get("natural") == "water":
                water.append(g)
            elif t.get("highway") in ("trunk", "primary", "secondary"):
                roads.append(g)
    return rivers, water, roads, places


def main():
    g = json.loads((GEO / "gcps.json").read_text())
    rivers, water, roads, places = load_osm(CTX / "osm_check.json")
    print(f"OSM: {len(rivers)} river ways, {len(water)} water, "
          f"{len(roads)} roads, {len(places)} places")

    for pg, d in sorted(g.items()):
        img = cv2.imread(str(SRC / f"page-{pg}.png"))
        img = cv2.resize(img, None, fx=SCALE, fy=SCALE, interpolation=cv2.INTER_AREA)
        h, w = img.shape[:2]
        Ai, ti = inverse(d["affine"])

        def to_px(pts):
            a = np.asarray(pts, float)
            xy = (a @ Ai.T + ti) * SCALE
            return xy.astype(np.int32)

        overlay = img.copy()
        for grp, col, th in ((water, (255, 190, 0), 2),
                             (rivers, (255, 130, 0), 2),
                             (roads, (0, 0, 255), 2)):
            for gm in grp:
                p = to_px(gm)
                if p[:, 0].max() < 0 or p[:, 1].max() < 0 or \
                   p[:, 0].min() > w or p[:, 1].min() > h:
                    continue
                cv2.polylines(overlay, [p], False, col, th, cv2.LINE_AA)
        for lon, lat, name in places:
            p = to_px([(lon, lat)])[0]
            if 0 <= p[0] < w and 0 <= p[1] < h:
                cv2.circle(overlay, tuple(p), 5, (0, 200, 0), -1)
                if name:
                    cv2.putText(overlay, name, (p[0] + 7, p[1] - 5),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.42, (0, 120, 0), 1,
                                cv2.LINE_AA)

        vis = cv2.addWeighted(overlay, 0.75, img, 0.25, 0)
        cv2.putText(vis, f"page-{pg}  rms {d['residual_rms_m']:.0f} m   "
                         f"OSM rivers/water = orange, roads = red, places = green",
                    (20, 34), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (0, 0, 0), 2, cv2.LINE_AA)
        cv2.imwrite(str(QA / f"verify_{pg}.jpg"), vis, [cv2.IMWRITE_JPEG_QUALITY, 88])
        print("wrote", QA / f"verify_{pg}.jpg")


if __name__ == "__main__":
    main()
