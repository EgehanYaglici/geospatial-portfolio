#!/usr/bin/env python3
"""
Step 4 - Write each sheet as a georeferenced GeoTIFF (EPSG:4326).

The fitted model is a plain affine, and a GDAL geotransform is exactly a plain
affine - including the two rotation terms. So the sheet is tagged in place
rather than warped: no resampling, no interpolation blur, and the pixels a
later step classifies are the original scanned pixels.

    X = GT0 + col*GT1 + row*GT2
    Y = GT3 + col*GT4 + row*GT5

Output: 02_georef/page-<n>_4326.tif
"""
import json
import pathlib

import numpy as np
import rasterio
from rasterio.transform import Affine

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "01_source"
OUT = ROOT / "02_georef"


def main():
    g = json.loads((OUT / "gcps.json").read_text())

    for pg, d in sorted(g.items()):
        M = np.array(d["affine"])
        transform = Affine(M[0, 0], M[0, 1], M[0, 2],
                           M[1, 0], M[1, 1], M[1, 2])
        with rasterio.open(SRC / f"page-{pg}.png") as src:
            data = src.read()
            prof = src.profile
        prof.update(driver="GTiff", crs="EPSG:4326", transform=transform,
                    compress="deflate", predictor=2, tiled=True,
                    blockxsize=512, blockysize=512, BIGTIFF="IF_SAFER")
        with rasterio.open(OUT / f"page-{pg}_4326.tif", "w", **prof) as dst:
            dst.write(data)

        h, w = data.shape[1], data.shape[2]
        pts = {k: (M[0, 0] * x + M[0, 1] * y + M[0, 2],
                   M[1, 0] * x + M[1, 1] * y + M[1, 2])
               for k, (x, y) in d["corners"].items()}
        res_x = abs(M[0, 0]) * 111320 * np.cos(np.radians(pts["tl"][1]))
        print(f"page-{pg}  {w}x{h}  ~{res_x:.0f} m/px  "
              f"rms {d['residual_rms_m']:.0f} m  max {d['residual_max_m']:.0f} m")
        print(f"   neatline  tl {pts['tl'][0]:.4f},{pts['tl'][1]:.4f}   "
              f"br {pts['br'][0]:.4f},{pts['br'][1]:.4f}")

    print("\nwrote GeoTIFFs to", OUT)


if __name__ == "__main__":
    main()
