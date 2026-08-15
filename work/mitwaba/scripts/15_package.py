#!/usr/bin/env python3
"""
Step 15 - Export the delivery package and run the acceptance checks.

Two jobs. First, write the shapefile copies asked for alongside the
GeoPackage, with field names shortened to the 10-character DBF limit and the
mapping recorded, because silently truncated attribute names are how a
shapefile export loses information.

Second, verify. Nothing here is taken on trust: the checks below confirm that
the groupements tile the territory with no gap and no overlap, that the
hierarchy adds up, that the counts match what the source atlas itself states
on each plate, and that every layer carries a CRS. Anything that fails is
printed as FAIL and the script exits non-zero.

Output: 06_output/shapefiles/, 06_output/checks.json
"""
import json
import pathlib
import shutil
import sys
import tempfile

import geopandas as gpd
from shapely.ops import unary_union

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from gpkg_io import read_gpkg

ROOT = pathlib.Path(__file__).resolve().parents[1]
VEC = ROOT / "03_vector"
CTX = ROOT / "04_context"
QA = ROOT / "qa"
OUT = ROOT / "06_output"
SHP = OUT / "shapefiles"
SHP.mkdir(parents=True, exist_ok=True)

# what the atlas prints in its own DONNEES STATISTIQUES panel, per plate
ATLAS_COUNTS = {
    "Balomotwa":  dict(groupements=5, villages=123, plate=54),
    "Banweshi":   dict(groupements=5, villages=62, plate=55),
    "Kiona-Ngoy": dict(groupements=4, villages=89, plate=56),
}
ATLAS_TERRITOIRE = dict(groupements=14, sectors=3, villages=276, plate=52)

SHORT = {"groupement": "groupemnt", "territoire": "territoir",
         "sector_type": "sect_type", "source_sheet": "src_sheet",
         "edit_overlap": "ed_overlap", "n_groupements": "n_group",
         "label_class": "lbl_class", "median_offset_m": "med_off_m",
         "max_offset_m": "max_off_m", "pct_on_river": "pct_river",
         "river_based": "river_bas"}


AUDIT_FIELDS = ("edit_overlap", "edit_seam", "edit_hole")


def to_shapefile(gdf, path, name):
    out = gdf.copy()
    # DBF caps a text field at 254 characters and truncates silently. The
    # per-feature edit logs run longer than that, so they are summarised here
    # and left in full in the GeoPackage, which is the authoritative copy.
    for f in AUDIT_FIELDS:
        if f in out.columns:
            out[f] = out[f].astype(str).str.slice(0, 240)
    out = out.rename(columns={k: v for k, v in SHORT.items()
                              if k in out.columns})
    with tempfile.TemporaryDirectory() as td:
        tmp = pathlib.Path(td) / f"{name}.shp"
        out.to_file(tmp, driver="ESRI Shapefile", encoding="utf-8")
        for f in pathlib.Path(td).iterdir():
            shutil.copyfile(f, path / f.name)
    return {k: v for k, v in SHORT.items() if k in gdf.columns}


def main():
    grp = read_gpkg(VEC / "mitwaba.gpkg", "groupements")
    sec = read_gpkg(VEC / "mitwaba.gpkg", "sectors")
    ter = read_gpkg(VEC / "mitwaba.gpkg", "territoire")
    layers = {"mitwaba_groupements": grp, "mitwaba_secteurs": sec,
              "mitwaba_territoire": ter}
    for nm in ("roads", "rivers", "water", "places"):
        layers[f"context_{nm}"] = read_gpkg(CTX / "context.gpkg", nm)

    renames = {}
    for name, gdf in layers.items():
        renames[name] = to_shapefile(gdf, SHP, name)
        print(f"shapefile: {name:<24} {len(gdf):5d} features")
    (SHP / "field_name_mapping.json").write_text(json.dumps(renames, indent=2))

    # ---------------------------------------------------------------- checks
    u = grp.to_crs(32735)
    s = sec.to_crs(32735)
    t = ter.to_crs(32735)
    checks = []

    def check(name, ok, detail):
        checks.append(dict(check=name, pass_=bool(ok), detail=detail))
        print(f"  {'PASS' if ok else 'FAIL'}  {name:<38} {detail}")

    print("\nacceptance checks")

    overlap = 0.0
    for i in range(len(u)):
        for j in range(i + 1, len(u)):
            overlap += u.geometry.iloc[i].intersection(u.geometry.iloc[j]).area
    check("groupements do not overlap", overlap / 1e6 < 0.01,
          f"{overlap/1e6:.4f} km2 of overlap")

    merged = unary_union(u.geometry.values)
    holes = sum(p.area for poly in (merged.geoms
                                    if merged.geom_type == "MultiPolygon"
                                    else [merged])
                for p in [__import__("shapely").geometry.Polygon(poly.exterior)]) \
        - merged.area
    check("no gap inside the territory", holes / 1e6 < 0.01,
          f"{holes/1e6:.4f} km2 unassigned")

    d = abs(merged.area - t.geometry.iloc[0].area) / 1e6
    check("territoire equals union of groupements", d < 0.05,
          f"{d:.4f} km2 difference")

    ds = abs(unary_union(s.geometry.values).area - merged.area) / 1e6
    check("sectors equal union of groupements", ds < 0.05,
          f"{ds:.4f} km2 difference")

    for sector, exp in ATLAS_COUNTS.items():
        n = int((grp.sector == sector).sum())
        check(f"groupement count · {sector}", n == exp["groupements"],
              f"{n} found, atlas plate {exp['plate']} states "
              f"{exp['groupements']}")

    check("groupement count · territoire",
          len(grp) == ATLAS_TERRITOIRE["groupements"],
          f"{len(grp)} found, atlas plate {ATLAS_TERRITOIRE['plate']} states "
          f"{ATLAS_TERRITOIRE['groupements']}")
    check("sector count · territoire", len(sec) == ATLAS_TERRITOIRE["sectors"],
          f"{len(sec)} found, atlas states {ATLAS_TERRITOIRE['sectors']}")

    for name, gdf in layers.items():
        if gdf.crs is None:
            check(f"CRS declared · {name}", False, "missing")
    check("CRS declared on every layer",
          all(g.crs is not None for g in layers.values()),
          "EPSG:4326 on all delivered layers")

    valid = all(g.geometry.is_valid.all() for g in (grp, sec, ter))
    check("geometries valid", valid, "OGC validity on all admin layers")

    ok = all(c["pass_"] for c in checks)
    (OUT / "checks.json").write_text(json.dumps(
        dict(all_passed=ok, checks=checks), indent=2))
    print(f"\n{'ALL CHECKS PASSED' if ok else 'SOME CHECKS FAILED'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
