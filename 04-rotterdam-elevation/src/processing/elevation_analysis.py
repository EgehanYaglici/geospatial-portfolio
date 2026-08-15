"""
elevation_analysis.py

Turns AHN DSM and DTM into per building heights for the Rotterdam study area.

The problem this solves
-----------------------
AHN's DTM is a bare earth product. It carries no returns underneath buildings,
so those cells are nodata: about 55 percent of this study area. A naive
`nDSM = DSM - DTM` therefore returns nodata over precisely the objects you
want to measure, and every building comes back with no height.

The fix is to close the terrain surface before subtracting. Under a building
footprint the true ground is very close to the street immediately around it,
especially in a polder city with under 15 m of relief, so a nearest valid
ground fill followed by a smoothing pass is an appropriate reconstruction.

Height estimator
----------------
Per footprint the nDSM pixel distribution is not a single value. The footprint
is first eroded by 1 m to step off the wall line, because edge pixels straddle
the facade and mix roof with pavement. The 90th percentile of the remaining
interior is taken as the height.

The choice matters. Over the same 1,740 footprints:

    estimator   median     max
    mean         13.4 m   109.2 m
    median       14.4 m   105.0 m
    p90          15.5 m   158.3 m
    max          16.3 m   173.9 m

The mean is dragged down by internal courtyards and setbacks. The maximum is
dragged up by masts, lift overruns and rooftop plant. The p90 sits on the main
roof plane, which is what "building height" normally means.

Outputs
-------
data/processed/ndsm.tif
data/processed/dtm_filled.tif
data/processed/buildings_heights.gpkg
outputs/web/data/buildings.geojson
outputs/tables/building_height_stats.json
outputs/tables/estimator_comparison.csv

Run
---
    python -m src.processing.elevation_analysis
"""

from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio.mask import mask
from scipy.ndimage import distance_transform_edt, uniform_filter
from shapely.geometry import mapping

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"
PROC = ROOT / "data" / "processed"
TABLES = ROOT / "outputs" / "tables"
WEB = ROOT / "outputs" / "web" / "data"

NODATA = -9999.0
EROSION_M = 1.0        # step off the facade before sampling the roof
SMOOTH_PX = 41         # 20.5 m at 0.5 m, wider than a typical Dutch block
MIN_PIXELS = 8         # below this the estimate is not trustworthy
ERA_BINS = [0, 1940, 1980, 2000, 2100]
ERA_LABELS = ["pre-1940", "1940-1980", "1980-2000", "2000+"]
HEIGHT_BINS = [0, 5, 10, 15, 20, 30, 50, 100, 250]


def _read(path: Path):
    with rasterio.open(path) as src:
        arr = src.read(1).astype(np.float32)
        arr = np.where(arr == src.nodata, np.nan, arr)
        return arr, src.profile.copy()


def build_ndsm() -> tuple[Path, dict]:
    dtm, profile = _read(RAW / "dtm.tif")
    dsm, _ = _read(RAW / "dsm.tif")

    holes = ~np.isfinite(dtm)
    hole_fraction = float(holes.mean())
    print(f"  DTM nodata: {holes.sum():,} px ({100 * hole_fraction:.1f}%). "
          f"This is the bare earth footprint gap, not a download error.")

    nearest = distance_transform_edt(holes, return_distances=False,
                                     return_indices=True)
    filled = dtm[tuple(nearest)]
    smoothed = uniform_filter(
        np.nan_to_num(filled, nan=float(np.nanmedian(filled))), size=SMOOTH_PX)
    dtm_filled = np.where(holes, smoothed, dtm).astype(np.float32)

    ndsm = np.where(np.isfinite(dsm), dsm - dtm_filled, np.nan).astype(np.float32)

    PROC.mkdir(parents=True, exist_ok=True)
    profile.update(nodata=NODATA, compress="deflate")
    for name, arr in (("dtm_filled", dtm_filled), ("ndsm", ndsm)):
        with rasterio.open(PROC / f"{name}.tif", "w", **profile) as dst:
            dst.write(np.where(np.isfinite(arr), arr, NODATA).astype(np.float32), 1)

    v = ndsm[np.isfinite(ndsm)]
    stats = {
        "dtm_hole_fraction": round(hole_fraction, 4),
        "ndsm_valid_fraction": round(float(v.size / ndsm.size), 4),
        "ndsm_min": round(float(v.min()), 2),
        "ndsm_max": round(float(v.max()), 2),
        "ndsm_mean": round(float(v.mean()), 2),
        "ndsm_median": round(float(np.median(v)), 2),
    }
    print(f"  nDSM: {stats['ndsm_min']} to {stats['ndsm_max']} m, "
          f"median {stats['ndsm_median']} m")
    return PROC / "ndsm.tif", stats


def zonal_heights(ndsm_path: Path) -> gpd.GeoDataFrame:
    gdf = gpd.read_file(RAW / "bag_pand.gpkg")
    rows = []
    with rasterio.open(ndsm_path) as src:
        nd = src.nodata
        for geom in gdf.geometry:
            inner = geom.buffer(-EROSION_M)
            use = inner if (not inner.is_empty and inner.area > 4) else geom
            try:
                arr, _ = mask(src, [mapping(use)], crop=True, nodata=nd, filled=True)
                v = arr[0]
                v = v[(v != nd) & np.isfinite(v)]
            except Exception:
                v = np.array([])
            if v.size:
                rows.append({
                    "n_px": int(v.size),
                    "h_mean": float(v.mean()),
                    "h_median": float(np.median(v)),
                    "h_p75": float(np.percentile(v, 75)),
                    "h_p90": float(np.percentile(v, 90)),
                    "h_max": float(v.max()),
                    "eroded": use is inner,
                })
            else:
                rows.append({"n_px": 0, "h_mean": np.nan, "h_median": np.nan,
                             "h_p75": np.nan, "h_p90": np.nan, "h_max": np.nan,
                             "eroded": False})

    gdf = pd.concat([gdf.reset_index(drop=True), pd.DataFrame(rows)], axis=1)
    gdf["footprint_m2"] = gdf.geometry.area
    gdf["height_m"] = gdf["h_p90"]
    gdf["reliable"] = gdf["n_px"] >= MIN_PIXELS
    gdf.loc[~gdf["reliable"], "height_m"] = np.nan
    return gpd.GeoDataFrame(gdf, geometry="geometry", crs="EPSG:28992")


def main() -> None:
    TABLES.mkdir(parents=True, exist_ok=True)
    WEB.mkdir(parents=True, exist_ok=True)

    print("[1/3] Building nDSM")
    ndsm_path, raster_stats = build_ndsm()

    print("[2/3] Zonal statistics over BAG footprints")
    gdf = zonal_heights(ndsm_path)
    ok = gdf[gdf.reliable]
    print(f"  {len(ok)} of {len(gdf)} footprints have at least {MIN_PIXELS} nDSM pixels "
          f"({100 * len(ok) / len(gdf):.1f}%)")

    comparison = pd.DataFrame({
        est: {
            "median_m": round(float(ok[col].median()), 2),
            "p90_m": round(float(ok[col].quantile(0.9)), 2),
            "max_m": round(float(ok[col].max()), 2),
            "share_below_1m_pct": round(float(100 * (ok[col] < 1).mean()), 2),
        }
        for est, col in [("mean", "h_mean"), ("median", "h_median"),
                         ("p75", "h_p75"), ("p90", "h_p90"), ("max", "h_max")]
    }).T
    comparison.index.name = "estimator"
    comparison.to_csv(TABLES / "estimator_comparison.csv")
    print("\n" + comparison.to_string())

    heights = ok["height_m"]
    hist, _ = np.histogram(heights.dropna(), bins=HEIGHT_BINS)
    era = pd.cut(ok["bouwjaar"], ERA_BINS, labels=ERA_LABELS)
    era_stats = ok.groupby(era, observed=False)["height_m"].agg(
        ["count", "median", "mean", "max"]).round(2)

    stats = {
        "raster": raster_stats,
        "footprints_total": int(len(gdf)),
        "footprints_measured": int(len(ok)),
        "measured_fraction": round(float(len(ok) / len(gdf)), 4),
        "estimator": f"p90 of nDSM inside footprint eroded by {EROSION_M} m",
        "height_median_m": round(float(heights.median()), 2),
        "height_mean_m": round(float(heights.mean()), 2),
        "height_max_m": round(float(heights.max()), 2),
        "above_50m": int((heights >= 50).sum()),
        "above_100m": int((heights >= 100).sum()),
        "height_distribution": {
            f"{HEIGHT_BINS[i]}-{HEIGHT_BINS[i + 1]}m": int(hist[i])
            for i in range(len(hist))
        },
        "by_era": {
            str(k): {kk: (None if pd.isna(vv) else float(vv)) for kk, vv in v.items()}
            for k, v in era_stats.to_dict("index").items()
        },
        "tallest": [
            {"bag_id": r.identificatie, "bouwjaar": int(r.bouwjaar),
             "height_m": round(float(r.height_m), 1),
             "max_nDSM_m": round(float(r.h_max), 1),
             "footprint_m2": round(float(r.footprint_m2), 1)}
            for r in ok.nlargest(10, "height_m").itertuples()
        ],
    }
    (TABLES / "building_height_stats.json").write_text(json.dumps(stats, indent=2))

    gdf.to_file(PROC / "buildings_heights.gpkg", driver="GPKG")
    web = ok[["identificatie", "bouwjaar", "height_m", "h_max",
              "footprint_m2", "geometry"]].copy()
    web["height_m"] = web["height_m"].round(1)
    web["h_max"] = web["h_max"].round(1)
    web["footprint_m2"] = web["footprint_m2"].round(0)
    web.to_crs(4326).to_file(WEB / "buildings.geojson", driver="GeoJSON")

    print(f"\n[3/3] median {stats['height_median_m']} m, max {stats['height_max_m']} m, "
          f"{stats['above_50m']} above 50 m, {stats['above_100m']} above 100 m")
    print("Wrote outputs/tables/building_height_stats.json and outputs/web/data/buildings.geojson")


if __name__ == "__main__":
    main()
