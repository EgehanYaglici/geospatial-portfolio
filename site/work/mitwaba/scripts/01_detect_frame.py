#!/usr/bin/env python3
"""
Step 1 - Detect the map neatline (frame) on each Mitwaba atlas sheet.

The CENI atlas sheets are photographs of a printed book. Each map carries a
thin black rectangular neatline; the graticule coordinate labels sit OUTSIDE
that frame (no tick marks are drawn across the neatline), so the frame plus the
label centroids are our geometric reference.

Detection strategy
------------------
1. Local-contrast dark mask (robust to the uneven lighting of a book photo).
2. Morphological opening with a very long kernel keeps only structures that
   span a large fraction of the sheet -> essentially only the neatline.
3. Projection profile of that mask gives sharp peaks at the four edges.
   Peaks are picked from the outside in, which avoids latching onto the book
   edge / page shadow (those are not long straight *dark lines* inside the
   image, and they get filtered by step 2 anyway).
4. Each edge is then refined by a robust straight-line fit inside a narrow
   band around its peak, so a slightly rotated or perspective-skewed page is
   still described exactly.

Output: 02_georef/frames.json  +  qa/frame_<page>.jpg overlay
"""
import json
import pathlib
import sys

import cv2
import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "01_source"
OUT = ROOT / "02_georef"
QA = ROOT / "qa"
OUT.mkdir(exist_ok=True)
QA.mkdir(exist_ok=True)

PAGES = ["21", "22", "23", "24"]
LONG_FRAC = 0.25      # a neatline edge spans >=25% of the sheet unbroken.
                      # Kept deliberately permissive: on several sheets the
                      # neatline is interrupted by an inset box or by weak
                      # printing, so demanding a longer run loses the edge.
                      # False positives are excluded by the outer-band search.
BAND = 18             # px half-width used for the refinement fit


def dark_mask(gray):
    """Pixels markedly darker than their local background."""
    fg = cv2.GaussianBlur(gray, (0, 0), 2)
    bg = cv2.GaussianBlur(gray, (0, 0), 61)
    return ((bg.astype(np.int16) - fg.astype(np.int16)) > 22).astype(np.uint8)


def long_lines(mask, horizontal):
    h, w = mask.shape
    n = int((w if horizontal else h) * LONG_FRAC)
    k = cv2.getStructuringElement(cv2.MORPH_RECT, (n, 1) if horizontal else (1, n))
    return cv2.morphologyEx(mask, cv2.MORPH_OPEN, k)


MARGIN_BAND = 0.20    # neatline always lies in the outer 20% of the sheet
EDGE_GUARD = 45       # ignore anything this close to the image border. The
                      # scan/page border artefact on page-23 is ~30px wide and
                      # outranks the real neatline on profile mass, so the
                      # guard has to clear it comfortably.


def edge_peaks(lm, horizontal, tag=""):
    """
    Return the coordinates of the two opposite neatline edges.

    Each edge is found independently as the strongest run of the projection
    profile inside the outer band on its own side. Searching per side (rather
    than thresholding globally) matters because one edge of a book photo is
    routinely lit or printed much weaker than the other, and a global
    threshold then drops it entirely. Runs sitting on the very border of the
    image are ignored: those are the page edge / binding shadow, not the
    neatline.
    """
    prof = lm.sum(axis=1 if horizontal else 0).astype(float)
    prof = cv2.GaussianBlur(prof.reshape(-1, 1), (1, 9), 0).ravel()
    if prof.max() <= 0:
        raise SystemExit(f"{tag}: no long lines found")
    n = len(prof)
    band = int(n * MARGIN_BAND)

    def best_run(lo, hi):
        seg = prof[lo:hi].copy()
        seg[: max(0, EDGE_GUARD - lo)] = 0
        seg[len(seg) - max(0, EDGE_GUARD - (n - hi)):] = 0
        if seg.max() <= 0:
            raise SystemExit(f"{tag}: empty search band {lo}:{hi}")
        strong = np.nonzero(seg > 0.5 * seg.max())[0]
        runs, cur = [], [strong[0]]
        for i in strong[1:]:
            if i - cur[-1] <= 12:
                cur.append(i)
            else:
                runs.append(cur)
                cur = [i]
        runs.append(cur)
        run = max(runs, key=lambda r: seg[r].sum())
        return lo + float(np.average(run, weights=seg[run]))

    return best_run(0, band), best_run(n - band, n)


def fit_edge(lm, centre, horizontal):
    """
    Robust straight-line fit to the mask pixels inside a band around `centre`.
    horizontal -> returns y = a*x + b ; vertical -> returns x = a*y + b
    """
    ys, xs = np.nonzero(lm)
    if horizontal:
        sel = np.abs(ys - centre) <= BAND
        u, v = xs[sel].astype(float), ys[sel].astype(float)
    else:
        sel = np.abs(xs - centre) <= BAND
        u, v = ys[sel].astype(float), xs[sel].astype(float)
    if len(u) < 200:
        raise SystemExit(f"too few pixels ({len(u)}) near {centre}")

    # collapse to one value per u so a thick line does not bias the fit
    order = np.argsort(u)
    u, v = u[order], v[order]
    uq, start = np.unique(u, return_index=True)
    end = np.append(start[1:], len(u))
    vq = np.array([v[s:e].mean() for s, e in zip(start, end)])

    keep = np.ones(len(uq), bool)
    for _ in range(4):
        a, b = np.polyfit(uq[keep], vq[keep], 1)
        r = vq - (a * uq + b)
        s = max(0.5, 1.4826 * np.median(np.abs(r[keep] - np.median(r[keep]))))
        keep = np.abs(r - np.median(r[keep])) < 3.0 * s
    a, b = np.polyfit(uq[keep], vq[keep], 1)
    r = vq[keep] - (a * uq[keep] + b)
    return dict(a=float(a), b=float(b), n=int(keep.sum()),
                rms=float(np.sqrt((r ** 2).mean())),
                span=[float(uq[keep].min()), float(uq[keep].max())])


def intersect(hl, vl):
    """hl: y = a1*x + b1 ; vl: x = a2*y + b2"""
    a1, b1, a2, b2 = hl["a"], hl["b"], vl["a"], vl["b"]
    y = (a1 * b2 + b1) / (1 - a1 * a2)
    return [float(a2 * y + b2), float(y)]


def main():
    summary = {}
    for pg in PAGES:
        img = cv2.imread(str(SRC / f"page-{pg}.png"), cv2.IMREAD_COLOR)
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        h, w = gray.shape
        m = dark_mask(gray)
        hm, vm = long_lines(m, True), long_lines(m, False)

        y_top, y_bot = edge_peaks(hm, True, f"page-{pg}/horiz")
        x_left, x_right = edge_peaks(vm, False, f"page-{pg}/vert")

        edges = {
            "top": fit_edge(hm, y_top, True),
            "bottom": fit_edge(hm, y_bot, True),
            "left": fit_edge(vm, x_left, False),
            "right": fit_edge(vm, x_right, False),
        }
        corners = {
            "tl": intersect(edges["top"], edges["left"]),
            "tr": intersect(edges["top"], edges["right"]),
            "br": intersect(edges["bottom"], edges["right"]),
            "bl": intersect(edges["bottom"], edges["left"]),
        }
        summary[pg] = dict(size=[w, h], edges=edges, corners=corners)

        vis = img.copy()
        pts = np.array([corners[k] for k in ("tl", "tr", "br", "bl")], np.int32)
        cv2.polylines(vis, [pts], True, (0, 0, 255), 5)
        for p in corners.values():
            cv2.circle(vis, (int(p[0]), int(p[1])), 16, (0, 200, 0), -1)
        s = 1400 / max(w, h)
        cv2.imwrite(str(QA / f"frame_{pg}.jpg"), cv2.resize(vis, (int(w * s), int(h * s))),
                    [cv2.IMWRITE_JPEG_QUALITY, 85])

        print(f"page-{pg}  {w}x{h}   peaks: y={y_top:.0f}/{y_bot:.0f} x={x_left:.0f}/{x_right:.0f}")
        for k, e in edges.items():
            print(f"   {k:<6} slope={e['a']:+.5f}  rms={e['rms']:.2f}px  n={e['n']}")
        print("   " + "  ".join(f"{k}=({p[0]:.1f},{p[1]:.1f})" for k, p in corners.items()))

    (OUT / "frames.json").write_text(json.dumps(summary, indent=2))
    print("\nwrote", OUT / "frames.json")


if __name__ == "__main__":
    sys.exit(main())
