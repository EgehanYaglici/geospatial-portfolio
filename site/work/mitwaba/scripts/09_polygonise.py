#!/usr/bin/env python3
"""
Step 9 - Turn the label rasters into groupement polygons.

Two things make the result topologically sound rather than merely tidy:

  * the boundary smoothing is done on the RASTER, with a majority filter, not
    on the polygons afterwards. Every pixel still ends up with exactly one
    label, so neighbouring groupements keep sharing an identical boundary. A
    smoothing pass applied to finished polygons treats each one separately and
    opens slivers along every shared edge;

  * simplification is Douglas-Peucker at a single tolerance. Polygonising one
    label raster gives neighbouring rings the same vertex sequence along their
    shared edge, and DP is deterministic, so both sides simplify identically
    and the edge stays shared.

The tolerance is set from what the source can actually support, not from what
looks smooth: the sheets are photographs of a 1:375 000 - 1:600 000 atlas
georeferenced to a few hundred metres, so detail below ~150 m is noise from
the halftone and the classifier, not cartography.

Output: 03_vector/groupements_raw.gpkg
"""
import json
import pathlib
import sys

import cv2
import geopandas as gpd
import numpy as np
import rasterio
from rasterio.features import shapes
from rasterio.transform import Affine
from shapely.geometry import shape
from shapely.ops import unary_union

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from gpkg_io import write_gpkg

ROOT = pathlib.Path(__file__).resolve().parents[1]
GEO = ROOT / "02_georef"
VEC = ROOT / "03_vector"

# which sector / chefferie each sheet carries, and its type
SHEET_META = {
    "22": ("Balomotwa", "Secteur"),
    "23": ("Banweshi", "Secteur"),
    "24": ("Kiona-Ngoy", "Chefferie"),
}

MAJORITY_R = 9          # radius of the boundary-smoothing majority filter, px
SIMPLIFY_M = 150.0      # Douglas-Peucker tolerance, metres
MIN_AREA_KM2 = 0.5      # drop scraps below this
UTM = "EPSG:32735"      # UTM 35S, the working CRS for anything metric here


def majority_filter(labels, radius):
    """
    Smooth class boundaries while keeping one label per pixel.

    Each class gets a box-filtered support and the winner is taken per pixel,
    which rounds off the staircase left by pixel-wise classification without
    ever leaving a pixel unassigned or doubly assigned.
    """
    k = 2 * radius + 1
    classes = [c for c in np.unique(labels) if c != 0]
    if not classes:
        return labels
    votes = np.stack([
        cv2.blur((labels == c).astype(np.float32), (k, k)) for c in classes
    ])
    win = np.array(classes, labels.dtype)[votes.argmax(0)]
    out = np.where(labels > 0, win, 0).astype(labels.dtype)
    # a pixel only changes hands if some class actually has support there
    out[votes.max(0) < 0.05] = 0
    return np.where(labels > 0, np.maximum(out, 0), 0).astype(labels.dtype)


def main():
    gcps = json.loads((GEO / "gcps.json").read_text())
    manifest = json.loads((VEC / "labels_manifest.json").read_text())

    rows = []
    for pg, (sector, sector_type) in SHEET_META.items():
        labels = np.load(VEC / f"labels_{pg}.npy")
        names = manifest[pg]["names"]
        M = np.array(gcps[pg]["affine"])
        transform = Affine(M[0, 0], M[0, 1], M[0, 2], M[1, 0], M[1, 1], M[1, 2])

        smooth = majority_filter(labels, MAJORITY_R)
        geoms = {}
        for geom, val in shapes(smooth, mask=smooth > 0, transform=transform,
                                connectivity=4):
            v = int(val)
            geoms.setdefault(v, []).append(shape(geom))

        for v, parts in sorted(geoms.items()):
            g = unary_union(parts).buffer(0)
            rows.append(dict(groupement=names[v - 1], sector=sector,
                             sector_type=sector_type, territoire="Mitwaba",
                             province="Haut-Katanga", source_sheet=f"page-{pg}",
                             geometry=g))
        print(f"page-{pg}: {len(geoms)} groupements polygonised")

    gdf = gpd.GeoDataFrame(rows, crs="EPSG:4326").to_crs(UTM)
    gdf["geometry"] = gdf.geometry.simplify(SIMPLIFY_M, preserve_topology=True)

    # drop scraps, keeping each groupement's substantive parts
    gdf["area_km2"] = gdf.area / 1e6
    keep = []
    for _, r in gdf.iterrows():
        g = r.geometry
        if g.geom_type == "MultiPolygon":
            big = [p for p in g.geoms if p.area / 1e6 >= MIN_AREA_KM2]
            g = unary_union(big) if big else max(g.geoms, key=lambda p: p.area)
        keep.append(g)
    gdf["geometry"] = keep
    gdf["area_km2"] = (gdf.area / 1e6).round(2)

    out = VEC / "groupements_raw.gpkg"
    write_gpkg(gdf, out, "groupements")

    print(f"\n{len(gdf)} groupements, {gdf.area_km2.sum():.0f} km2 total")
    for sector, grp in gdf.groupby("sector"):
        print(f"  {sector:<12} {len(grp)} groupements  {grp.area_km2.sum():8.0f} km2")
        for _, r in grp.sort_values("area_km2", ascending=False).iterrows():
            print(f"      {r.groupement:<10} {r.area_km2:8.1f} km2")
    print("\nwrote", out)


if __name__ == "__main__":
    main()
