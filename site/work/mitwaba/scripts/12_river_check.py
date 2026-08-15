#!/usr/bin/env python3
"""
Step 12 - Check the boundaries that follow rivers, and flag the rest.

The brief asks specifically for this: where a boundary runs along a river in
the CENI atlas, the digitised line and the modern watercourse should agree,
and any disagreement should be called out rather than quietly smoothed over.

Method. Every boundary is sampled at fixed intervals and each sample measured
to the nearest OSM watercourse. A sample is then

    following   < 400 m   the boundary is on the river
    offset      < 1500 m  it clearly shadows a river but sits beside it
    independent otherwise the boundary is not a river boundary at all

A boundary counts as river-based when most of its length is following or
offset. For those, the offset portion is what needs review: it is either a
digitising error, a georeferencing residual, or a river that has genuinely
moved or is mapped differently in OSM. The distinction cannot be made from
the data alone, so the segments are exported for inspection rather than
silently adjusted.

Output: qa/river_check.gpkg, qa/river_check.json, and the numbers used in the
uncertainty note delivered with the map.
"""
import json
import pathlib
import sys

import geopandas as gpd
import numpy as np
from shapely.geometry import LineString, MultiLineString, Point
from shapely.ops import linemerge, unary_union

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from gpkg_io import append_gpkg, read_gpkg

ROOT = pathlib.Path(__file__).resolve().parents[1]
VEC = ROOT / "03_vector"
CTX = ROOT / "04_context"
QA = ROOT / "qa"
UTM = "EPSG:32735"

STEP_M = 250.0            # boundary sampling interval
FOLLOW_M = 400.0          # on the river
OFFSET_M = 1500.0         # shadowing the river
RIVER_SHARE = 0.55        # fraction of samples needed to call it river-based


def shared_edges(gdf):
    """Every boundary line, tagged with the two groupements it separates."""
    edges = []
    for i in range(len(gdf)):
        for j in range(i + 1, len(gdf)):
            a, b = gdf.iloc[i], gdf.iloc[j]
            if not a.geometry.intersects(b.geometry):
                continue
            inter = a.geometry.boundary.intersection(b.geometry.boundary)
            if inter.is_empty:
                continue
            lines = [g for g in getattr(inter, "geoms", [inter])
                     if g.geom_type in ("LineString", "MultiLineString")]
            if not lines:
                continue
            geom = linemerge(unary_union(lines))
            if geom.is_empty or geom.length < STEP_M:
                continue
            edges.append(dict(left=a.groupement, right=b.groupement,
                              left_sector=a.sector, right_sector=b.sector,
                              geometry=geom))
    return gpd.GeoDataFrame(edges, crs=gdf.crs)


def sample(geom, step):
    parts = geom.geoms if geom.geom_type == "MultiLineString" else [geom]
    pts = []
    for p in parts:
        n = max(2, int(p.length // step) + 1)
        pts += [p.interpolate(d) for d in np.linspace(0, p.length, n)]
    return pts


def main():
    g = read_gpkg(VEC / "mitwaba.gpkg", "groupements").to_crs(UTM)
    rivers = read_gpkg(CTX / "context.gpkg", "rivers").to_crs(UTM)
    water = read_gpkg(CTX / "context.gpkg", "water").to_crs(UTM)

    hydro = gpd.GeoSeries(
        list(rivers.geometry) + [w.boundary for w in water.geometry],
        crs=UTM)
    sindex = hydro.sindex
    print(f"{len(g)} groupements, {len(hydro)} hydrographic features")

    edges = shared_edges(g)
    print(f"{len(edges)} shared boundaries, "
          f"{edges.length.sum()/1000:.0f} km total")

    rows, flagged = [], []
    for _, e in edges.iterrows():
        pts = sample(e.geometry, STEP_M)
        d = []
        for p in pts:
            idx = list(sindex.nearest(p, max_distance=OFFSET_M * 2,
                                      return_all=False)[1])
            d.append(min((hydro.iloc[i].distance(p) for i in idx), default=1e9))
        d = np.asarray(d)
        follow = float((d < FOLLOW_M).mean())
        offset = float(((d >= FOLLOW_M) & (d < OFFSET_M)).mean())
        river_based = (follow + offset) >= RIVER_SHARE
        rows.append(dict(
            left=e.left, right=e.right, length_km=round(e.geometry.length / 1000, 1),
            river_based=bool(river_based),
            pct_on_river=round(100 * follow), pct_offset=round(100 * offset),
            median_offset_m=round(float(np.median(d[d < 1e8])) if (d < 1e8).any() else -1),
            max_offset_m=round(float(d[d < OFFSET_M].max()) if (d < OFFSET_M).any() else -1),
            geometry=e.geometry))
        if river_based and offset > 0.20:
            seg = [pts[k] for k in range(len(pts))
                   if FOLLOW_M <= d[k] < OFFSET_M]
            if len(seg) >= 2:
                flagged.append(dict(
                    left=e.left, right=e.right,
                    pct_offset=round(100 * offset),
                    median_offset_m=round(float(np.median(d[(d >= FOLLOW_M) &
                                                            (d < OFFSET_M)]))),
                    geometry=MultiLineString([LineString(seg)])
                    if len(seg) > 1 else LineString(seg)))

    res = gpd.GeoDataFrame(rows, crs=UTM)
    out = QA / "river_check.gpkg"
    append_gpkg(res.to_crs(4326), out, "boundaries", fresh=True)
    if flagged:
        append_gpkg(gpd.GeoDataFrame(flagged, crs=UTM).to_crs(4326),
                    out, "flagged_segments")

    rb = res[res.river_based]
    summary = dict(
        boundaries=len(res), total_km=round(res.length_km.sum(), 1),
        river_based=len(rb), river_based_km=round(rb.length_km.sum(), 1),
        flagged=len(flagged))
    (QA / "river_check.json").write_text(json.dumps(
        dict(summary=summary,
             boundaries=res.drop(columns="geometry").to_dict("records")),
        indent=2))

    print(f"\nriver-based boundaries: {len(rb)} of {len(res)} "
          f"({rb.length_km.sum():.0f} of {res.length_km.sum():.0f} km)")
    print(f"segments flagged for review: {len(flagged)}\n")
    for _, r in res.sort_values("length_km", ascending=False).iterrows():
        tag = "river" if r.river_based else "  -  "
        print(f"  {tag}  {r.left:<10}/{r.right:<10} {r.length_km:6.1f} km  "
              f"on-river {r.pct_on_river:3d}%  offset {r.pct_offset:3d}%  "
              f"median {r.median_offset_m:5d} m")
    print("\nwrote", out)


if __name__ == "__main__":
    main()
