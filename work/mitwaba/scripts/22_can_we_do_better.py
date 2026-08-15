#!/usr/bin/env python3
"""
Step 22 - Is the georeferencing worth improving, and by what?

Before spending effort on a fancier transform it is worth knowing whether the
error is structured or random.

  * Structured error - residuals that grow towards the edges, or all lean the
    same way - means the model is too simple for the paper. Page curvature and
    camera perspective do exactly that, and a projective or polynomial fit
    would absorb them.

  * Random scatter means the model already describes the sheet, and the
    residual is measurement noise in locating the label centres. No transform
    can remove that; only a better source image or more control can.

So: refit each sheet, then test the residuals for (a) correlation with
position, which detects tilt or curvature, and (b) a common offset, which
detects a datum or systematic reading error. The verdict tells us which of the
two situations we are in, and therefore whether more work would pay.
"""
import json
import pathlib
import sys

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

ROOT = pathlib.Path(__file__).resolve().parents[1]
GEO = ROOT / "02_georef"
QA = ROOT / "qa"

SHEETS = ["21", "22", "23", "24"]
NAMES = {"21": "pl.52 Territoire 1:1M", "22": "pl.54 Balomotwa 1:600k",
         "23": "pl.55 Banweshi 1:400k", "24": "pl.56 Kiona-Ngoy 1:375k"}


def main():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "g", ROOT / "scripts" / "03_build_gcps.py")
    g = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(g)

    frames = json.loads((GEO / "frames.json").read_text())
    gcps = json.loads((GEO / "gcps.json").read_text())
    import cv2
    report = {}

    for pg in SHEETS:
        img = cv2.imread(str(ROOT / "01_source" / f"page-{pg}.png"))
        h, w = img.shape[:2]
        lons, lats = g.SHEETS[pg]
        fr = frames[pg]

        cons = []
        for side in ("top", "bottom", "left", "right"):
            axis = 0 if side in ("top", "bottom") else 1
            values = lons if axis == 0 else lats
            pts, frame = g.side_points(img, fr["edges"][side], side,
                                       fr["corners"])
            order = sorted(range(len(pts)), key=lambda i: pts[i]["rect"])
            fit = g.fit_lattice([pts[i]["rect"] for i in order], len(values),
                                frame)
            if fit is None:
                continue
            vidx, step, keep = fit
            cen = np.array([pts[i]["rect"] for i in order])
            if keep.sum() >= 4:
                kk, cc = vidx[keep], cen[keep]
                sl = [(cc[j] - cc[i]) / (kk[j] - kk[i])
                      for i in range(len(kk)) for j in range(i + 1, len(kk))
                      if kk[j] != kk[i]]
                al = float(np.median(sl))
                bl = float(np.median(cc - al * kk))
                dev = np.abs(cen - (al * vidx + bl))
                keep = keep & (dev < max(12.0, 0.025 * al))
            for rank, i in enumerate(order):
                if keep[rank] and not pts[i]["clipped"]:
                    cons.append((pts[i]["orig"][0], pts[i]["orig"][1], axis,
                                 values[vidx[rank]]))

        theta = g.page_rotation(fr["edges"])
        M, _ = g.fit_rectified(cons, theta, (w / 2.0, h / 2.0))

        rows = []
        for x, y, axis, v in cons:
            lon, lat = g.apply_M(M, x, y)
            err_deg = (lon if axis == 0 else lat) - v
            m_per_deg = (111320 * np.cos(np.radians(np.mean(lats)))
                         if axis == 0 else 110570)
            rows.append((x / w - 0.5, y / h - 0.5, axis, err_deg * m_per_deg))
        R = np.array(rows)
        if len(R) < 6:
            continue

        res = R[:, 3]
        # does the error lean with position? that is curvature / perspective
        rx = np.corrcoef(R[:, 0], res)[0, 1]
        ry = np.corrcoef(R[:, 1], res)[0, 1]
        # is there a common shift? that would be a datum or reading offset
        bias = res.mean()
        spread = res.std()
        # quadratic term: does |error| grow towards the edges?
        rad = np.hypot(R[:, 0], R[:, 1])
        rq = np.corrcoef(rad, np.abs(res))[0, 1]

        structured = max(abs(rx), abs(ry), abs(rq)) > 0.45
        report[pg] = dict(
            sheet=NAMES[pg], n=len(R), rms_m=round(float(np.sqrt((res**2).mean())), 1),
            bias_m=round(float(bias), 1), spread_m=round(float(spread), 1),
            corr_x=round(float(rx), 2), corr_y=round(float(ry), 2),
            corr_radial=round(float(rq), 2),
            diagnosis=("structured - a higher-order transform would help"
                       if structured else
                       "random scatter - the model already fits the sheet"))

        print(f"{NAMES[pg]:<26} n={len(R):3d}  rms {report[pg]['rms_m']:6.0f} m")
        print(f"   common shift (datum-like)      {bias:+8.1f} m")
        print(f"   scatter about that shift       {spread:8.1f} m")
        print(f"   error vs x / y / radius        {rx:+.2f} / {ry:+.2f} / {rq:+.2f}")
        print(f"   -> {report[pg]['diagnosis']}")

    (QA / "improvement_potential.json").write_text(json.dumps(report, indent=2))
    print("\nwrote", QA / "improvement_potential.json")


if __name__ == "__main__":
    main()
