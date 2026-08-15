#!/usr/bin/env python3
"""
Step 20 - Independent accuracy test of the georeferencing.

Why this exists. The residuals in step 3 are the fit measured against the very
points it was fitted to, so they say how self-consistent the model is and
nothing about whether it is right. A mis-read label, or a lattice that slid by
one node, would produce a beautiful residual and a map in the wrong place.

This test uses no control point at all. It detects the linework the atlas
itself printed - the red road network and the blue watercourses - converts
those pixels to ground coordinates through the fitted model, and measures how
far they land from the same features in present-day OpenStreetMap. Roads and
rivers were never used to fit anything, so agreement here is independent
evidence that the sheets are placed correctly.

Reading the numbers: the roads should agree to within roughly the
georeferencing error plus the width of a drawn line at map scale. Rivers are
looser by nature - a 1:600 000 sheet generalises a meander that OSM traces in
full - so their spread is expected to be wider and is reported separately.

Two things had to be controlled for or the test measures the wrong thing.

The reference data is the FULL OpenStreetMap extract, not the copy clipped to
the territory that the map uses: the source plates show a wide surrounding
area, and scoring a printed road there against a clipped layer matches it to
whatever unrelated road happens to be nearest.

And the printed linework is thinned to its centreline first. At 1:600 000 a
road is drawn about a millimetre wide, which is 600 m on the ground, so an
untinned pixel can sit 300 m from the true centre before any georeferencing
error is involved at all. That is also why a few hundred metres is this test's
floor, not a defect: it is the width of the pen.

Only pixels with a mapped counterpart within MAX_PAIR_M are scored: a road on
the 2016 sheet that OSM has never mapped would otherwise be counted as a huge
error when it is really an absence of reference data.

Output: qa/georef_independent.json + qa/georef_independent_<page>.jpg
"""
import json
import pathlib
import sys

import cv2
import geopandas as gpd
import numpy as np
from shapely.geometry import LineString, MultiLineString
from shapely.ops import unary_union
from shapely.strtree import STRtree

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from gpkg_io import read_gpkg

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "01_source"
GEO = ROOT / "02_georef"
CTX = ROOT / "04_context"
QA = ROOT / "qa"

SHEETS = ["22", "23", "24"]
UTM = "EPSG:32735"
MAX_PAIR_M = 4000.0     # beyond this we assume OSM simply has no counterpart
SUBSAMPLE = 2500        # pixels scored per theme per sheet


def detect_red(bgr):
    """The atlas prints its road network in red; nothing else on the sheet is."""
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    h, s, v = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
    return (((h < 12) | (h > 168)) & (s > 90) & (v > 60)).astype(np.uint8)


def detect_blue(bgr):
    """Watercourses are the only saturated cyan-blue linework."""
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    h, s, v = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
    return ((h > 88) & (h < 118) & (s > 55) & (v > 90)).astype(np.uint8)


def load_reference(path):
    """OSM roads and watercourses over the whole extract, in UTM."""
    d = json.loads(pathlib.Path(path).read_text())
    roads, hydro = [], []
    for e in d["elements"]:
        t = e.get("tags", {})
        if e["type"] == "node" or "geometry" not in e:
            continue
        pts = [(p["lon"], p["lat"]) for p in e["geometry"]]
        if len(pts) < 2:
            continue
        if "highway" in t:
            roads.append(LineString(pts))
        elif t.get("waterway") in ("river", "stream") or t.get("natural") == "water":
            hydro.append(LineString(pts))
    to_utm = lambda gs: list(gpd.GeoSeries(gs, crs=4326).to_crs(UTM))
    return to_utm(roads), to_utm(hydro)


def skeleton(mask):
    """
    Thin the printed linework to one-pixel centrelines.

    Without this the measurement is dominated by how wide the atlas draws its
    roads rather than by where it puts them.
    """
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


def main():
    gcps = json.loads((GEO / "gcps.json").read_text())
    frames = json.loads((GEO / "frames.json").read_text())
    boxes = json.loads((ROOT / "03_vector/boxes.json").read_text())

    road_geoms, hydro_geoms = load_reference(CTX / "osm_full.json")
    print(f"reference: {len(road_geoms)} OSM road ways, "
          f"{len(hydro_geoms)} watercourses (full extract, unclipped)")
    road_tree = STRtree(road_geoms)
    hydro_tree = STRtree(hydro_geoms)

    rng = np.random.default_rng(0)
    report = {}

    for pg in SHEETS:
        img = cv2.imread(str(SRC / f"page-{pg}.png"))
        h, w = img.shape[:2]
        M = np.array(gcps[pg]["affine"])

        # inside the neatline, minus the printed panels (their legend swatches
        # and locator maps carry the same red and blue)
        corners = np.array([frames[pg]["corners"][k]
                            for k in ("tl", "tr", "br", "bl")], np.int32)
        inside = np.zeros((h, w), np.uint8)
        cv2.fillPoly(inside, [corners], 1)
        cv2.rectangle(inside, (0, 0), (w - 1, h - 1), 0, 30)
        for bx, by, bw, bh in boxes.get(pg, {}).get("boxes", []):
            inside[max(0, by - 8):by + bh + 8, max(0, bx - 8):bx + bw + 8] = 0

        out = {}
        vis = img.copy()
        for theme, mask_fn, tree, geoms, col in (
                ("roads", detect_red, road_tree, road_geoms, (0, 255, 255)),
                ("hydrography", detect_blue, hydro_tree, hydro_geoms, (0, 255, 0))):
            m = (mask_fn(img) & inside).astype(np.uint8)
            m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
            m = skeleton(m)
            ys, xs = np.nonzero(m)
            if len(xs) < 200:
                out[theme] = dict(pixels=int(len(xs)), note="too few pixels")
                continue
            pick = rng.choice(len(xs), size=min(SUBSAMPLE, len(xs)),
                              replace=False)
            xs, ys = xs[pick], ys[pick]

            lon = M[0, 0] * xs + M[0, 1] * ys + M[0, 2]
            lat = M[1, 0] * xs + M[1, 1] * ys + M[1, 2]
            pts = gpd.GeoSeries(gpd.points_from_xy(lon, lat),
                                crs=4326).to_crs(UTM)

            d = []
            for p in pts:
                idx = np.atleast_1d(tree.query_nearest(p,
                                                       max_distance=MAX_PAIR_M))
                if idx.size == 0:
                    continue
                d.append(min(geoms[int(i)].distance(p) for i in idx))
            d = np.asarray(d)
            if d.size == 0:
                out[theme] = dict(pixels=int(len(xs)), note="no counterpart")
                continue
            out[theme] = dict(
                pixels_detected=int(m.sum()),
                scored=int(d.size),
                matched_pct=round(100 * d.size / len(xs), 1),
                median_m=round(float(np.median(d)), 1),
                p75_m=round(float(np.percentile(d, 75)), 1),
                p90_m=round(float(np.percentile(d, 90)), 1),
                within_500m_pct=round(float((d < 500).mean() * 100), 1),
                within_1km_pct=round(float((d < 1000).mean() * 100), 1))
            for x, y in zip(xs[::4], ys[::4]):
                cv2.circle(vis, (int(x), int(y)), 3, col, -1)

        report[f"page-{pg}"] = out
        s = 1500 / max(h, w)
        cv2.imwrite(str(QA / f"georef_independent_{pg}.jpg"),
                    cv2.resize(vis, None, fx=s, fy=s),
                    [cv2.IMWRITE_JPEG_QUALITY, 85])

        r, y = out.get("roads", {}), out.get("hydrography", {})
        print(f"page-{pg}")
        for nm, st in (("printed roads vs OSM roads", r),
                       ("printed streams vs OSM hydro", y)):
            if "median_m" in st:
                print(f"   {nm:<30} median {st['median_m']:6.0f} m   "
                      f"p90 {st['p90_m']:6.0f} m   "
                      f"<500 m {st['within_500m_pct']:5.1f}%   "
                      f"({st['scored']} points, {st['matched_pct']}% matched)")
            else:
                print(f"   {nm:<30} {st}")

    (QA / "georef_independent.json").write_text(json.dumps(report, indent=2))
    print("\nwrote", QA / "georef_independent.json")


if __name__ == "__main__":
    main()
