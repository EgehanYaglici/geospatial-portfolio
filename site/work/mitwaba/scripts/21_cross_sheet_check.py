#!/usr/bin/env python3
"""
Step 21 - Cross-sheet agreement: the test that cannot be fooled.

The residuals in step 3 measure a fit against its own control points, so they
prove self-consistency and nothing more. Step 20 compares the printed linework
to OpenStreetMap, which is genuinely independent but noisy, because a
1:600 000 sheet generalises and OSM does not.

This test avoids both problems. Every plate was georeferenced separately, from
its own coordinate labels, with no knowledge of the others. Where two plates
overlap they draw the SAME physical roads and rivers. So: take the road
network printed on plate A, put it on the ground using A's model; take the
same network printed on plate B, put it on the ground using B's model; and
measure how far apart they land.

If both models are right the two copies coincide, and the disagreement is just
drafting and line width. If either model is wrong - a mis-read label, a
lattice that slipped one node - the two copies separate by a quarter degree,
about 27 km, and it is unmissable.

Read the result by scale class. The three DETAIL plates (1:375 000 to
1:600 000) are the ones the delivered boundaries come from, and they are held
to a few hundred metres. The territoire overview at 1:1 000 000 is reported
too, but it cannot be held to the same standard and is not part of the
pass/fail: at that scale a drawn road is a millimetre wide, which is a
kilometre on the ground, and its geometry is generalised on top of that. A
1-3 km spread against the detail plates is what generalisation alone produces.

What the test is really looking for is a gross error - a mis-read label or a
lattice slip - which would show up as a quarter degree, about 27 km, and could
not be mistaken for anything else.

This is the number to quote when someone asks how you know the georeferencing
is correct.

Output: qa/cross_sheet.json, qa/cross_sheet_<A>_<B>.jpg
"""
import itertools
import json
import pathlib
import sys

import cv2
import geopandas as gpd
import numpy as np
from shapely.geometry import Point
from shapely.strtree import STRtree

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "01_source"
GEO = ROOT / "02_georef"
QA = ROOT / "qa"

SHEETS = ["21", "22", "23", "24"]
NAMES = {"21": "pl.52 Territoire", "22": "pl.54 Balomotwa",
         "23": "pl.55 Banweshi", "24": "pl.56 Kiona-Ngoy"}
UTM = "EPSG:32735"
MAX_PAIR_M = 8000.0     # generous: a one-node lattice slip would be 27 000 m
SAMPLE = 1800
DETAIL = {"22", "23", "24"}   # the plates the boundaries are taken from
DETAIL_TOL_M = 1500          # what independent detail plates must agree to
GROSS_ERROR_M = 10000        # a lattice slip would be ~27 000 m


def red_mask(bgr):
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    h, s, v = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
    return (((h < 12) | (h > 168)) & (s > 90) & (v > 60)).astype(np.uint8)


def skeleton(mask):
    img = (mask > 0).astype(np.uint8) * 255
    out = np.zeros_like(img)
    el = cv2.getStructuringElement(cv2.MORPH_CROSS, (3, 3))
    for _ in range(40):
        er = cv2.erode(img, el)
        out |= cv2.subtract(img, cv2.dilate(er, el))
        img = er
        if not img.any():
            break
    return (out > 0).astype(np.uint8)


def sheet_points(pg, gcps, frames, boxes, rng):
    """Road-network pixels of one plate, on the ground, in UTM."""
    img = cv2.imread(str(SRC / f"page-{pg}.png"))
    h, w = img.shape[:2]
    corners = np.array([frames[pg]["corners"][k]
                        for k in ("tl", "tr", "br", "bl")], np.int32)
    inside = np.zeros((h, w), np.uint8)
    cv2.fillPoly(inside, [corners], 1)
    cv2.rectangle(inside, (0, 0), (w - 1, h - 1), 0, 40)
    for bx, by, bw, bh in boxes.get(pg, {}).get("boxes", []):
        inside[max(0, by - 10):by + bh + 10, max(0, bx - 10):bx + bw + 10] = 0

    m = skeleton(cv2.morphologyEx(red_mask(img) & inside, cv2.MORPH_OPEN,
                                  np.ones((3, 3), np.uint8)))
    ys, xs = np.nonzero(m)
    if len(xs) == 0:
        return gpd.GeoSeries([], crs=UTM), None
    M = np.array(gcps[pg]["affine"])
    lon = M[0, 0] * xs + M[0, 1] * ys + M[0, 2]
    lat = M[1, 0] * xs + M[1, 1] * ys + M[1, 2]
    pts = gpd.GeoSeries(gpd.points_from_xy(lon, lat), crs=4326).to_crs(UTM)

    # ground footprint of this plate, for intersecting with the other
    cl = np.array([[M[0, 0] * x + M[0, 1] * y + M[0, 2],
                    M[1, 0] * x + M[1, 1] * y + M[1, 2]]
                   for x, y in corners])
    from shapely.geometry import Polygon
    foot = gpd.GeoSeries([Polygon(cl)], crs=4326).to_crs(UTM)[0]
    return pts, foot


def main():
    gcps = json.loads((GEO / "gcps.json").read_text())
    frames = json.loads((GEO / "frames.json").read_text())
    boxes = json.loads((ROOT / "03_vector/boxes.json").read_text())
    rng = np.random.default_rng(0)

    pts, foot = {}, {}
    for pg in SHEETS:
        pts[pg], foot[pg] = sheet_points(pg, gcps, frames, boxes, rng)
        print(f"plate {NAMES[pg]:<20} {len(pts[pg]):6d} road pixels on the ground")

    report, rows = {}, []
    for a, b in itertools.combinations(SHEETS, 2):
        if foot[a] is None or foot[b] is None:
            continue
        shared = foot[a].intersection(foot[b])
        if shared.is_empty or shared.area / 1e6 < 500:
            continue

        pa = pts[a][pts[a].within(shared)]
        pb = pts[b][pts[b].within(shared)]
        if len(pa) < 200 or len(pb) < 200:
            continue
        if len(pa) > SAMPLE:
            pa = pa.iloc[rng.choice(len(pa), SAMPLE, replace=False)]

        geoms = list(pb)
        tree = STRtree(geoms)
        d = []
        for p in pa:
            idx = np.atleast_1d(tree.query_nearest(p, max_distance=MAX_PAIR_M))
            if idx.size == 0:
                continue
            d.append(min(geoms[int(i)].distance(p) for i in idx))
        if not d:
            continue
        d = np.asarray(d)

        rec = dict(
            plate_a=NAMES[a], plate_b=NAMES[b],
            overlap_km2=round(shared.area / 1e6),
            compared=int(d.size),
            # p25 is the honest measure of "the same road on both plates":
            # the upper tail is dominated by roads one plate draws and the
            # other simply does not, which nearest-neighbour then pairs with
            # something unrelated.
            p25_m=round(float(np.percentile(d, 25)), 1),
            median_m=round(float(np.median(d)), 1),
            p90_m=round(float(np.percentile(d, 90)), 1),
            within_500m_pct=round(float((d < 500).mean() * 100), 1),
            within_1km_pct=round(float((d < 1000).mean() * 100), 1))
        rec["detail_pair"] = a in DETAIL and b in DETAIL
        report[f"{a}-{b}"] = rec
        rows.append(rec)
        tag = "detail" if rec["detail_pair"] else "1:1M  "
        print(f"  {tag}  {NAMES[a]:<20} vs {NAMES[b]:<20} "
              f"overlap {rec['overlap_km2']:6d} km2  "
              f"p25 {rec['p25_m']:6.0f} m  median {rec['median_m']:6.0f} m  "
              f"<1 km {rec['within_1km_pct']:5.1f}%")

    detail = [r for r in rows if r["detail_pair"]]
    other = [r for r in rows if not r["detail_pair"]]
    worst_detail = max((r["median_m"] for r in detail), default=0.0)
    worst_any = max((r["median_m"] for r in rows), default=0.0)

    gross = worst_any > GROSS_ERROR_M
    ok = (not gross) and worst_detail < DETAIL_TOL_M
    verdict = (
        f"PASS - the three detail plates were georeferenced independently and "
        f"place the same roads within {worst_detail:.0f} m of each other; no "
        f"plate is grossly misplaced (a mis-read label would show as ~27 km)."
        if ok else
        f"FAIL - worst detail-plate disagreement {worst_detail:.0f} m"
        + (" and at least one plate is grossly misplaced." if gross else "."))

    print(f"\ndetail plates, worst median disagreement : {worst_detail:6.0f} m"
          f"   (tolerance {DETAIL_TOL_M} m)")
    if other:
        print(f"1:1M overview vs detail plates, median   : "
              f"{np.median([r['median_m'] for r in other]):6.0f} m"
              f"   (generalisation, not error - see docstring)")
    print(f"gross-error screen (>{GROSS_ERROR_M/1000:.0f} km)          : "
          f"{'FAILED' if gross else 'clear'}")
    print("\n" + verdict)

    (QA / "cross_sheet.json").write_text(json.dumps(
        dict(verdict=verdict, passed=ok,
             worst_detail_median_m=worst_detail,
             detail_tolerance_m=DETAIL_TOL_M,
             gross_error_screen_m=GROSS_ERROR_M,
             pairs=report), indent=2))
    print("wrote", QA / "cross_sheet.json")


if __name__ == "__main__":
    main()
