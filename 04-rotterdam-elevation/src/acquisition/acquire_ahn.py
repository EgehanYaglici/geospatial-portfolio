"""
acquire_ahn.py

Downloads real AHN elevation rasters and real BAG building footprints for the
Rotterdam study area.

This script replaces an earlier version that fell back to a synthetic
`_create_demonstration_raster()` when PDOK was unreachable. That fallback was
removed deliberately: it produced random rectangles with `np.random.seed(42)`
and wrote them to disk under the same filenames as real data, so every
downstream product silently became fiction. A download failure must fail
loudly instead.

Sources
-------
AHN  : PDOK WCS, https://service.pdok.nl/rws/ahn/wcs/v1_0
       coverages `dsm_05m` and `dtm_05m`, 0.5 m, EPSG:28992 (RD New)
BAG  : PDOK WFS, https://service.pdok.nl/lv/bag/wfs/v2_0
       feature type `bag:pand`, carries `bouwjaar` (construction year)

Both are Dutch open government data.

Outputs
-------
data/raw/dsm.tif          mosaicked AHN DSM
data/raw/dtm.tif          mosaicked AHN DTM, with its native holes intact
data/raw/bag_pand.gpkg    building footprints with construction year
metadata/acquisition_metadata.json

Run
---
    python -m src.acquisition.acquire_ahn
"""

from __future__ import annotations

import itertools
import json
import subprocess
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio.transform import from_origin

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"
META = ROOT / "metadata"

# Rotterdam: the bombed centre (Coolsingel, Laurenskwartier) together with the
# Kop van Zuid high rise cluster. 1500 x 1500 m in RD New.
AOI = (92_000, 435_800, 93_500, 437_300)
RES = 0.5
TILE = 750           # WCS request size in metres, keeps each response modest
NODATA = -9999.0

WCS = "https://service.pdok.nl/rws/ahn/wcs/v1_0"
BAG_WFS = "https://service.pdok.nl/lv/bag/wfs/v2_0"
TIMEOUT = 180


def _curl(url: str, out: Path | None = None) -> tuple[str, str]:
    """Return (http_code, body). Writes to `out` when given."""
    cmd = ["curl", "-sS", "--max-time", str(TIMEOUT)]
    if out is not None:
        cmd += ["-o", str(out), "-w", "%{http_code}"]
    cmd.append(url)
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"curl failed: {r.stderr.strip()}")
    return (r.stdout.strip(), "") if out is not None else ("200", r.stdout)


def fetch_coverage(coverage: str, name: str) -> Path:
    """Download a coverage as tiles and mosaic them onto the AOI grid."""
    tiles_dir = RAW / "_tiles"
    tiles_dir.mkdir(parents=True, exist_ok=True)

    width = int((AOI[2] - AOI[0]) / RES)
    height = int((AOI[3] - AOI[1]) / RES)
    out = np.full((height, width), np.nan, dtype=np.float32)

    origins = list(itertools.product(
        range(AOI[0], AOI[2], TILE), range(AOI[1], AOI[3], TILE)))
    for i, (x0, y0) in enumerate(origins):
        path = tiles_dir / f"{coverage}_{i}.tif"
        url = (f"{WCS}?SERVICE=WCS&VERSION=2.0.1&REQUEST=GetCoverage"
               f"&COVERAGEID={coverage}"
               f"&SUBSET=x({x0},{x0 + TILE})&SUBSET=y({y0},{y0 + TILE})"
               f"&FORMAT=image/tiff")
        code, _ = _curl(url, path)
        size = path.stat().st_size if path.exists() else 0
        if code != "200" or size < 10_000:
            sys.exit(f"PDOK WCS returned {code} for {coverage} tile {i} "
                     f"({size} bytes). Refusing to continue: there is no "
                     f"synthetic fallback by design.")
        print(f"    {coverage} tile {i + 1}/{len(origins)}  {size / 1e6:5.1f} MB")

        with rasterio.open(path) as src:
            arr = src.read(1).astype(np.float32)
            arr[arr > 1e30] = np.nan                     # PDOK uses float max
            if src.nodata is not None:
                arr[arr == src.nodata] = np.nan
            b = src.bounds
            col = int(round((b.left - AOI[0]) / RES))
            row = int(round((AOI[3] - b.top) / RES))
            h, w = arr.shape
            target = out[row:row + h, col:col + w]
            sub = arr[:target.shape[0], :target.shape[1]]
            good = np.isfinite(sub)
            target[good] = sub[good]

    profile = dict(driver="GTiff", height=height, width=width, count=1,
                   dtype="float32", crs="EPSG:28992",
                   transform=from_origin(AOI[0], AOI[3], RES, RES),
                   nodata=NODATA, compress="deflate")
    dest = RAW / f"{name}.tif"
    with rasterio.open(dest, "w", **profile) as dst:
        dst.write(np.where(np.isfinite(out), out, NODATA).astype(np.float32), 1)

    valid = out[np.isfinite(out)]
    print(f"    -> {dest.name}  {width}x{height}  valid {100 * valid.size / out.size:.1f}%  "
          f"range {valid.min():.2f} to {valid.max():.2f} m")
    return dest


def fetch_bag() -> Path:
    """Download BAG building footprints with construction year, paging the WFS."""
    base = (f"{BAG_WFS}?service=WFS&version=2.0.0&request=GetFeature"
            f"&typeNames=bag:pand&outputFormat=application/json"
            f"&srsName=EPSG:28992"
            f"&bbox={AOI[0]},{AOI[1]},{AOI[2]},{AOI[3]},EPSG:28992")
    features, start, page = [], 0, 1000
    while True:
        _, body = _curl(f"{base}&count={page}&startIndex={start}")
        batch = json.loads(body).get("features", [])
        features += batch
        print(f"    BAG page at {start}: {len(batch)} features "
              f"(total {len(features)})")
        if len(batch) < page:
            break
        start += page
        if start > 50_000:
            raise RuntimeError("BAG paging did not terminate")

    if not features:
        sys.exit("PDOK BAG WFS returned no features. Refusing to continue.")

    gdf = gpd.GeoDataFrame.from_features(features, crs="EPSG:28992")
    gdf = gdf[gdf.geometry.notna() & gdf.geometry.is_valid].copy()
    gdf["bouwjaar"] = pd.to_numeric(gdf["bouwjaar"], errors="coerce")
    dest = RAW / "bag_pand.gpkg"
    gdf.to_file(dest, driver="GPKG")
    print(f"    -> {dest.name}  {len(gdf)} footprints, "
          f"bouwjaar {int(gdf.bouwjaar.min())} to {int(gdf.bouwjaar.max())}")
    return dest


def main() -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    META.mkdir(parents=True, exist_ok=True)

    print("[1/3] AHN DSM from PDOK WCS")
    fetch_coverage("dsm_05m", "dsm")
    print("[2/3] AHN DTM from PDOK WCS")
    fetch_coverage("dtm_05m", "dtm")
    print("[3/3] BAG footprints from PDOK WFS")
    fetch_bag()

    with rasterio.open(RAW / "dsm.tif") as s:
        dsm = s.read(1)
        dsm_valid = float(np.isfinite(np.where(dsm == NODATA, np.nan, dsm)).mean())
    with rasterio.open(RAW / "dtm.tif") as s:
        dtm = s.read(1)
        dtm_valid = float(np.isfinite(np.where(dtm == NODATA, np.nan, dtm)).mean())

    (META / "acquisition_metadata.json").write_text(json.dumps({
        "aoi_bbox_rd": list(AOI),
        "crs": "EPSG:28992",
        "resolution_m": RES,
        "raster_size": f"{int((AOI[2]-AOI[0])/RES)}x{int((AOI[3]-AOI[1])/RES)}",
        "dsm_source": "PDOK AHN WCS, coverage dsm_05m",
        "dtm_source": "PDOK AHN WCS, coverage dtm_05m",
        "footprint_source": "PDOK BAG WFS, bag:pand",
        "dsm_valid_fraction": round(dsm_valid, 4),
        "dtm_valid_fraction": round(dtm_valid, 4),
        "synthetic_fallback": False,
        "note": ("The DTM is bare earth, so it carries no returns beneath "
                 "buildings. Its low valid fraction is expected and is handled "
                 "in elevation_analysis.py, not here."),
    }, indent=2))
    print("\nWrote metadata/acquisition_metadata.json")


if __name__ == "__main__":
    main()
