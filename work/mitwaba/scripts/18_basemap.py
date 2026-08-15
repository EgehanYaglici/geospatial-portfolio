#!/usr/bin/env python3
"""
Step 18 - Build a terrain basemap for the map sheet.

The brief asks for the subdivisions to sit on a modern basemap and for the
sheet to read like a road map. The roads, hydrography and settlements do most
of that, but on a territory that is 200 km of plateau and river valley a plain
flat fill still looks like a diagram. A quiet hillshade underneath gives the
sheet its terrain without competing with the administrative colours - which is
exactly what the client's own reference map does.

Elevation comes from the public AWS terrain tiles (SRTM/NED derived, ODbL /
public domain depending on tile). Tiles are fetched at zoom 10, about 150 m on
the ground here, mosaicked, reprojected to UTM 35S and shaded.

Output: 04_context/hillshade_utm35s.tif
"""
import io
import math
import pathlib
import sys
import urllib.request

import numpy as np
import rasterio
from rasterio.merge import merge
from rasterio.warp import Resampling, calculate_default_transform, reproject

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from gpkg_io import read_gpkg

ROOT = pathlib.Path(__file__).resolve().parents[1]
VEC = ROOT / "03_vector"
CTX = ROOT / "04_context"
TILES = CTX / "terrain_tiles"
TILES.mkdir(parents=True, exist_ok=True)

URL = "https://s3.amazonaws.com/elevation-tiles-prod/geotiff/{z}/{x}/{y}.tif"
ZOOM = 10
PAD_DEG = 0.15
AZIMUTH, ALTITUDE, ZFACTOR = 315.0, 45.0, 1.4
UTM = "EPSG:32735"


def tile_range(minx, miny, maxx, maxy, z):
    n = 2 ** z

    def xt(lon):
        return int((lon + 180.0) / 360.0 * n)

    def yt(lat):
        r = math.radians(lat)
        return int((1.0 - math.log(math.tan(r) + 1 / math.cos(r)) / math.pi)
                   / 2.0 * n)

    return (xt(minx), xt(maxx), yt(maxy), yt(miny))


def fetch(z, x, y):
    p = TILES / f"{z}_{x}_{y}.tif"
    if p.exists() and p.stat().st_size > 0:
        return p
    req = urllib.request.Request(URL.format(z=z, x=x, y=y),
                                 headers={"User-Agent": "mitwaba-map/1.0"})
    with urllib.request.urlopen(req, timeout=40) as r:
        p.write_bytes(r.read())
    return p


def hillshade(dem, res, az=AZIMUTH, alt=ALTITUDE, z=ZFACTOR):
    dy, dx = np.gradient(dem.astype(np.float32) * z, res, res)
    slope = np.arctan(np.hypot(dx, dy))
    aspect = np.arctan2(-dx, dy)
    a, e = math.radians(360.0 - az + 90.0), math.radians(alt)
    hs = (np.sin(e) * np.cos(slope)
          + np.cos(e) * np.sin(slope) * np.cos(a - aspect))
    return np.clip(hs, 0, 1)


def main():
    ter = read_gpkg(VEC / "mitwaba.gpkg", "territoire")
    minx, miny, maxx, maxy = ter.total_bounds
    minx, miny = minx - PAD_DEG, miny - PAD_DEG
    maxx, maxy = maxx + PAD_DEG, maxy + PAD_DEG

    x0, x1, y0, y1 = tile_range(minx, miny, maxx, maxy, ZOOM)
    want = [(ZOOM, x, y) for x in range(x0, x1 + 1) for y in range(y0, y1 + 1)]
    print(f"terrain tiles: z{ZOOM}  x {x0}-{x1}  y {y0}-{y1}  = {len(want)}")

    paths, failed = [], 0
    for z, x, y in want:
        try:
            paths.append(fetch(z, x, y))
        except Exception:
            failed += 1
    print(f"fetched {len(paths)} tiles ({failed} unavailable)")
    if not paths:
        raise SystemExit("no terrain tiles could be fetched")

    srcs = [rasterio.open(p) for p in paths]
    mosaic, transform = merge(srcs)
    prof = srcs[0].profile
    for s in srcs:
        s.close()

    dst_crs = UTM
    t, w, h = calculate_default_transform(
        prof["crs"], dst_crs, mosaic.shape[2], mosaic.shape[1],
        *rasterio.transform.array_bounds(mosaic.shape[1], mosaic.shape[2],
                                         transform),
        resolution=120)
    dem = np.zeros((h, w), np.float32)
    reproject(mosaic[0], dem, src_transform=transform, src_crs=prof["crs"],
              dst_transform=t, dst_crs=dst_crs, resampling=Resampling.bilinear)

    dem[dem < -1000] = np.nan
    dem = np.nan_to_num(dem, nan=float(np.nanmedian(dem)))
    hs = (hillshade(dem, 120.0) * 255).astype(np.uint8)

    out = CTX / "hillshade_utm35s.tif"
    with rasterio.open(out, "w", driver="GTiff", height=h, width=w, count=1,
                       dtype="uint8", crs=dst_crs, transform=t,
                       compress="deflate", tiled=True) as d:
        d.write(hs, 1)
    print(f"wrote {out}  ({w} x {h} @ 120 m, elevation "
          f"{dem.min():.0f}-{dem.max():.0f} m)")


if __name__ == "__main__":
    main()
