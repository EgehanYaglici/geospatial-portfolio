#!/usr/bin/env python3
"""
Step 10 - Reconcile the three sector sheets into one seamless dataset.

Within a sheet the groupements already tile perfectly - they came out of a
single label raster. Between sheets they cannot: Balomotwa, Banweshi and
Kiona-Ngoy were drawn at 1:600 000, 1:400 000 and 1:375 000, photographed
separately, and georeferenced independently to between 190 m and 830 m. Their
common boundaries therefore disagree by a few hundred metres, leaving overlaps
in some places and slivers of nothing in others.

Resolved by accuracy, not by arbitration. Where two sheets claim the same
ground, the sheet whose own georeferencing residual is smaller keeps it -
page 22 at 188 m outranks page 24 at 317 m, which outranks page 23 at 829 m.
Where neither claims it, the gap goes to whichever sector already surrounds
most of it, measured by shared boundary length. Both rules are recorded per
feature so the edits can be audited.

Then the hierarchy is built by dissolving upwards, so a territoire boundary is
by construction the union of its sectors and can never disagree with them.

Output: 03_vector/mitwaba.gpkg  (groupements, sectors, territoire)
"""
import json
import pathlib
import sys

import cv2
import geopandas as gpd
import numpy as np
from shapely.geometry import Polygon
from shapely.ops import unary_union

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from gpkg_io import append_gpkg, read_gpkg

ROOT = pathlib.Path(__file__).resolve().parents[1]
GEO = ROOT / "02_georef"
VEC = ROOT / "03_vector"

SNAP_M = 5000.0        # gaps wider than this are real, not a registration seam.
                       # Set from the observed disagreement between sheets:
                       # welding at 2 km left a visible notch where Balomotwa
                       # and Banweshi meet, 5 km closes it for 0.2% of area.
MIN_PART_CELLS = 500   # 5 km2 at the 100 m regularisation grid
UTM = "EPSG:32735"


def priority(gcps):
    """Sheets ranked by their own georeferencing residual, best first."""
    return sorted(gcps, key=lambda pg: gcps[pg]["residual_rms_m"])


def resolve_overlaps(gdf, order):
    """Give contested ground to the better-registered sheet."""
    out = gdf.copy()
    notes = {i: [] for i in out.index}
    for rank, better in enumerate(order):
        for worse in order[rank + 1:]:
            a = out.index[out.source_sheet == f"page-{better}"]
            b = out.index[out.source_sheet == f"page-{worse}"]
            if len(a) == 0 or len(b) == 0:
                continue
            keep = unary_union(out.loc[a, "geometry"].values)
            for j in b:
                g = out.at[j, "geometry"]
                if not g.intersects(keep):
                    continue
                lost = g.intersection(keep).area / 1e6
                if lost <= 0:
                    continue
                out.at[j, "geometry"] = g.difference(keep)
                notes[j].append(f"-{lost:.1f} km2 to page-{better}")
    out["edit_overlap"] = [", ".join(notes[i]) or "none" for i in out.index]
    return out


def fill_seams(gdf, snap_m):
    """
    Close the registration seams between sheets.

    The union of the sectors is buffered out and back, which welds anything
    narrower than the buffer into one piece; whatever that adds over the raw
    union is seam. Each seam piece is then given to the groupement it shares
    the most boundary with, so the join follows the existing line rather than
    cutting a new one.
    """
    union = unary_union(gdf.geometry.values)
    welded = union.buffer(snap_m / 2, join_style=2).buffer(-snap_m / 2, join_style=2)
    seams = welded.difference(union)
    if seams.is_empty:
        gdf["edit_seam"] = "none"
        return gdf, 0.0

    pieces = list(seams.geoms) if seams.geom_type == "MultiPolygon" else [seams]
    out = gdf.copy()
    notes = {i: [] for i in out.index}
    total = 0.0
    for piece in pieces:
        if piece.area < 1.0:
            continue
        near = out.index[out.geometry.distance(piece) < snap_m]
        if len(near) == 0:
            continue
        share = {i: out.at[i, "geometry"].buffer(1.0).intersection(piece).area
                 for i in near}
        j = max(share, key=share.get)
        out.at[j, "geometry"] = unary_union([out.at[j, "geometry"], piece]).buffer(0)
        notes[j].append(f"+{piece.area/1e6:.2f} km2")
        total += piece.area / 1e6
    out["edit_seam"] = [", ".join(notes[i]) or "none" for i in out.index]
    return out, total


def fill_enclosed(gdf, step=250.0):
    """
    Allocate ground that is enclosed by the territory but claimed by nobody.

    One such area survives the seam welding: about 360 km2 west of Mufunga,
    where the MUFUNGA enlargement panel on plate 54 covers the map underneath,
    so Balomotwa has no boundary there at all, and plate 55 stops short of it
    from the south. It is not a registration seam - the source simply does not
    show it - so it is filled by proximity, each point going to the nearest
    groupement, and the affected features are tagged. The result is a map with
    no hole in it and a note saying which boundary was interpolated rather
    than read.
    """
    # Holes of the UNION, not of each feature. The unclaimed ground sits
    # between two groupements, so no single polygon has a hole there; it only
    # appears once they are merged.
    union = unary_union(gdf.geometry.values)
    polys = union.geoms if union.geom_type == "MultiPolygon" else [union]
    holes = unary_union([Polygon(p.exterior) for p in polys]).difference(union)
    pieces = [p for p in (holes.geoms if holes.geom_type == "MultiPolygon"
                          else [holes]) if p.area > 1e6]
    out = gdf.copy()
    notes = {i: [] for i in out.index}
    total = 0.0
    for piece in pieces:
        minx, miny, maxx, maxy = piece.bounds
        xs = np.arange(minx, maxx + step, step)
        ys = np.arange(miny, maxy + step, step)
        gx, gy = np.meshgrid(xs, ys)
        pts = gpd.GeoSeries(gpd.points_from_xy(gx.ravel(), gy.ravel()),
                            crs=out.crs)
        pts = pts[pts.within(piece)]
        if pts.empty:
            continue
        near = gpd.sjoin_nearest(gpd.GeoDataFrame(geometry=pts),
                                 out[["geometry"]], how="left")
        cells = gpd.GeoDataFrame(
            geometry=[p.buffer(step / 2, cap_style=3) for p in near.geometry],
            crs=out.crs)
        cells["owner"] = near["index_right"].values
        for owner, grp in cells.groupby("owner"):
            add = unary_union(grp.geometry.values).intersection(piece)
            if add.is_empty:
                continue
            j = int(owner)
            out.at[j, "geometry"] = unary_union(
                [out.at[j, "geometry"], add]).buffer(0)
            notes[j].append(f"+{add.area/1e6:.1f} km2")
            total += add.area / 1e6
    out["edit_hole"] = [", ".join(notes[i]) or "none" for i in out.index]
    return out, total


def regularise(gdf, cell=100.0, smooth=7):
    """
    Final pass: rasterise the whole layer, smooth, and polygonise once.

    The harmonisation edits above are set operations, and set operations leave
    marks - a staircase where the unclaimed area was filled cell by cell, a
    hairline where an overlap was cut away, a spike where two sheets crossed
    at a shallow angle. Rounding the whole layer through a single grid removes
    all of them in one consistent way, and because every cell carries exactly
    one groupement the output is guaranteed to tile the territory with no gap
    and no overlap.

    The grid is 100 m, well inside the 200-800 m the georeferencing itself is
    good to, so this costs nothing real.
    """
    from rasterio.features import rasterize, shapes as rshapes
    from rasterio.transform import from_origin
    from shapely.geometry import shape as to_shape

    minx, miny, maxx, maxy = gdf.total_bounds
    pad = cell * 4
    minx, miny, maxx, maxy = minx - pad, miny - pad, maxx + pad, maxy + pad
    w = int(np.ceil((maxx - minx) / cell))
    h = int(np.ceil((maxy - miny) / cell))
    transform = from_origin(minx, maxy, cell, cell)

    grid = rasterize([(g, i + 1) for i, g in enumerate(gdf.geometry)],
                     out_shape=(h, w), transform=transform, fill=0,
                     all_touched=False, dtype="int32")

    if smooth:
        k = 2 * smooth + 1
        classes = [c for c in np.unique(grid) if c != 0]
        votes = np.stack([cv2.blur((grid == c).astype(np.float32), (k, k))
                          for c in classes])
        win = np.array(classes, grid.dtype)[votes.argmax(0)]
        grid = np.where(grid > 0, win, 0).astype(grid.dtype)

    # Drop detached scraps before the sweep. The atlas shows each groupement
    # as one piece; the few sub-5 km2 islands left here are classifier noise
    # and edits, not cartography, and blanking them lets the sweep below give
    # the ground to whichever groupement actually surrounds it.
    for c in [c for c in np.unique(grid) if c != 0]:
        m = (grid == c).astype(np.uint8)
        n, comp, stats, _ = cv2.connectedComponentsWithStats(m, 8)
        if n <= 2:
            continue
        keep = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
        for i in range(1, n):
            if i != keep and stats[i, cv2.CC_STAT_AREA] < MIN_PART_CELLS:
                grid[comp == i] = 0

    # Sweep up any cell left unassigned inside the body. The proximity fill
    # above works on a coarser grid and leaves specks along its own edges -
    # 67 of them, 3 km2 in total, which the acceptance check reads as gaps in
    # the coverage. Anything enclosed by the territory takes the label of its
    # nearest neighbour, so the tiling ends up complete by construction.
    body = (grid > 0).astype(np.uint8)
    ff = np.zeros((h + 2, w + 2), np.uint8)
    outside = (1 - body).copy()
    cv2.floodFill(outside, ff, (0, 0), 2)
    enclosed = ((body > 0) | (outside != 2))
    unknown = (enclosed & (grid == 0)).astype(np.uint8)
    if unknown.any():
        _, lbl = cv2.distanceTransformWithLabels(
            unknown, cv2.DIST_L2, 3, labelType=cv2.DIST_LABEL_PIXEL)
        known = np.flatnonzero((grid > 0).ravel())
        lut = np.zeros(int(lbl.max()) + 1, grid.dtype)
        lut[lbl.ravel()[known]] = grid.ravel()[known]
        grid = np.where(grid > 0, grid, np.where(enclosed, lut[lbl], 0))

    parts = {}
    for geom, val in rshapes(grid, mask=grid > 0, transform=transform,
                             connectivity=4):
        parts.setdefault(int(val), []).append(to_shape(geom))

    # Deliberately NOT simplified afterwards. Douglas-Peucker runs on a whole
    # ring, and two neighbours traverse their shared edge as parts of
    # different rings, so they choose different vertices to keep and the edge
    # stops being shared - which showed up as 9 km2 of overlap and 11 km2 of
    # gap in the acceptance checks. The majority filter has already done the
    # smoothing; the remaining 100 m steps are 0.2 mm at the printed scale.
    out = gdf.copy()
    for i in range(len(out)):
        out.iat[i, out.columns.get_loc("geometry")] = \
            unary_union(parts.get(i + 1, [])).buffer(0)
    return out


def main():
    gcps = json.loads((GEO / "gcps.json").read_text())
    gdf = read_gpkg(VEC / "groupements_raw.gpkg", "groupements")
    if gdf.crs is None or gdf.crs.to_epsg() != 32735:
        gdf = gdf.to_crs(UTM)

    order = [pg for pg in priority(gcps) if pg != "21"]
    print("sheet priority (best georeferencing first):")
    for pg in order:
        print(f"   page-{pg}  rms {gcps[pg]['residual_rms_m']:.0f} m")

    before = gdf.area.sum() / 1e6
    gdf = resolve_overlaps(gdf, order)
    mid = gdf.area.sum() / 1e6
    gdf, seam_km2 = fill_seams(gdf, SNAP_M)
    gdf, hole_km2 = fill_enclosed(gdf)
    gdf = regularise(gdf)
    after = gdf.area.sum() / 1e6
    print(f"\noverlap removed : {before - mid:8.1f} km2")
    print(f"seam filled     : {seam_km2:8.1f} km2")
    print(f"enclosed filled : {hole_km2:8.1f} km2")
    print(f"total area      : {after:8.1f} km2")

    gdf["area_km2"] = (gdf.area / 1e6).round(2)
    gdf["level"] = "Groupement"
    gdf = gdf[["province", "territoire", "sector_type", "sector", "groupement",
               "level", "area_km2", "source_sheet", "edit_overlap", "edit_seam",
               "edit_hole",
               "geometry"]]

    sectors = (gdf.dissolve(by=["sector", "sector_type"], as_index=False)
                  [["sector", "sector_type", "geometry"]])
    sectors["province"] = "Haut-Katanga"
    sectors["territoire"] = "Mitwaba"
    sectors["level"] = sectors["sector_type"]
    sectors["area_km2"] = (sectors.area / 1e6).round(2)
    sectors["n_groupements"] = [int((gdf.sector == s).sum()) for s in sectors.sector]

    terr = gpd.GeoDataFrame(
        [dict(province="Haut-Katanga", territoire="Mitwaba", level="Territoire",
              n_sectors=len(sectors), n_groupements=len(gdf),
              geometry=unary_union(sectors.geometry.values).buffer(0))],
        crs=gdf.crs)
    terr["area_km2"] = (terr.area / 1e6).round(2)

    out = VEC / "mitwaba.gpkg"
    append_gpkg(gdf.to_crs(4326), out, "groupements", fresh=True)
    append_gpkg(sectors.to_crs(4326), out, "sectors")
    append_gpkg(terr.to_crs(4326), out, "territoire")

    print("\nsectors:")
    for _, r in sectors.iterrows():
        print(f"   {r.sector_type} {r['sector']:<12} {r.n_groupements} groupements"
              f"  {r.area_km2:8.0f} km2")
    print(f"\nterritoire Mitwaba: {terr.area_km2.iloc[0]:.0f} km2, "
          f"{len(sectors)} sectors, {len(gdf)} groupements")
    print("wrote", out)


if __name__ == "__main__":
    main()
