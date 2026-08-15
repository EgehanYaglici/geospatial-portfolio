#!/usr/bin/env python3
"""
Step 3 - Turn the graticule labels into ground control points.

The label VALUES are declared below. They were read directly off the rectified
margin strips produced by 02a_dump_bands.py (see qa/bands/) rather than taken
from OCR: the text is 8 pt, photographed through a bound book, and OCR was not
dependable enough to be the authority for a coordinate. The label POSITIONS
are still measured automatically, which is where the precision actually
matters.

Method
------
For every sheet:
  * rectify each margin so its neatline edge is axis-aligned,
  * find the label blocks in a narrow strip (narrow enough to exclude the sheet
    title above and the folio line below),
  * take each block's centre - that is where the meridian / parallel meets the
    frame - and rotate it back into original page pixels,
  * pair the top and bottom point of equal longitude into a meridian, and the
    left and right point of equal latitude into a parallel,
  * intersect every meridian with every parallel.

Each intersection is a point whose page pixel and true (lon, lat) are both
known: a GCP. A 7 x 6 sheet therefore yields 42 well distributed GCPs, which is
far more than any transform here needs and lets the residuals mean something.

Output: 02_georef/gcps_<page>.json  +  qa/gcp_<page>.jpg
"""
import json
import pathlib
import re
import subprocess
import sys

import cv2
import numpy as np

DMS = re.compile(r"(\d{1,3})\s*[°º]?\s*(\d{1,2})?\s*['’]?\s*(\d{1,2})?\s*[\"”]?\s*([NSEW])")


def parse_dms(text):
    m = DMS.search(text.replace("O", "0").replace(" ", ""))
    if not m:
        return None
    v = float(m.group(1)) + float(m.group(2) or 0) / 60 + float(m.group(3) or 0) / 3600
    return -v if m.group(4) in ("S", "W") else v

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "01_source"
OUT = ROOT / "02_georef"
QA = ROOT / "qa"

# ---------------------------------------------------------------- label values
# Longitudes are listed left -> right, latitudes top -> bottom, as printed.
# Verified against qa/bands/<page>_<side>.png for all four sides of each sheet.
def seq(start, stop, step):
    n = int(round((stop - start) / step)) + 1
    return [round(start + i * step, 6) for i in range(n)]


SHEETS = {
    # page: (longitudes L->R, latitudes T->B)   step is 15' = 0.25 deg
    "21": (seq(25.75, 28.50, 0.25), seq(-8.00, -10.50, -0.25)),
    "22": (seq(26.50, 28.00, 0.25), seq(-8.75, -10.00, -0.25)),
    "23": (seq(26.25, 27.25, 0.25), seq(-9.50, -10.25, -0.25)),
    "24": (seq(27.00, 28.00, 0.25), seq(-8.00, -8.75, -0.25)),
}

# how far outside the neatline to search, in page pixels. Generous, because
# the exact row of label text is then located automatically inside this window
# (see locate_text_line) - a fixed window either clips the labels on one sheet
# or swallows the sheet title on another.
STRIP = {"top": (6, 118), "bottom": (6, 118), "left": (6, 118), "right": (6, 118)}

MIN_BLOCK = 26      # a label is at least this long along the frame
MIN_INK = 200       # and carries at least this much ink
GAP_CLOSE = 21      # bridge the gaps between characters of one label
LINE_PAD = 6        # rows kept either side of the detected text line
CLIP_EDGE = 8       # a block this close to the strip end is cut off


# ------------------------------------------------------------------- geometry
def rot_matrix(edge, side, w, h):
    a, b = edge["a"], edge["b"]
    ang = np.degrees(np.arctan(a))
    if side in ("top", "bottom"):
        c = (w / 2.0, a * (w / 2.0) + b)
        return cv2.getRotationMatrix2D(c, ang, 1.0), c
    c = (a * (h / 2.0) + b, h / 2.0)
    return cv2.getRotationMatrix2D(c, -ang, 1.0), c


def inv_affine(M):
    A = np.vstack([M, [0, 0, 1]])
    return np.linalg.inv(A)


def ink_mask(strip):
    g = cv2.cvtColor(strip, cv2.COLOR_BGR2GRAY)
    bg = cv2.GaussianBlur(g, (0, 0), 25)
    return ((bg.astype(np.int16) - g.astype(np.int16)) > 26).astype(np.uint8)


def locate_text_line(ink, along_axis, near_side):
    """
    Find the band of rows (or columns) holding the coordinate labels.

    The search window has to be wide enough not to clip the labels, which means
    it also catches the sheet title above the frame and the folio line below.
    Those are separate lines of text, so we take the ink cluster CLOSEST to the
    neatline and keep only that. near_side says which end of the window the
    neatline is on.
    """
    prof = ink.sum(axis=1) if along_axis == 0 else ink.sum(axis=0)
    if prof.max() <= 0:
        return None
    on = prof > 0.12 * prof.max()
    runs, i, n = [], 0, len(on)
    while i < n:
        if on[i]:
            j = i
            while j < n and on[j]:
                j += 1
            if j - i >= 6:
                runs.append((i, j))
            i = j
        else:
            i += 1
    if not runs:
        return None
    return runs[0] if near_side == "low" else runs[-1]


def find_blocks(strip, along_axis, near_side):
    ink = ink_mask(strip)
    line = locate_text_line(ink, along_axis, near_side)
    if line is None:
        return []
    a, b = line
    if along_axis == 0:
        sub = ink[max(0, a - LINE_PAD):b + LINE_PAD, :]
        prof = sub.sum(axis=0)
    else:
        sub = ink[:, max(0, a - LINE_PAD):b + LINE_PAD]
        prof = sub.sum(axis=1)
    on = (prof > 0).astype(np.uint8).reshape(-1, 1)
    on = cv2.morphologyEx(on, cv2.MORPH_CLOSE, np.ones((GAP_CLOSE, 1), np.uint8)).ravel()
    blocks, i, n = [], 0, len(on)
    while i < n:
        if on[i]:
            j = i
            while j < n and on[j]:
                j += 1
            if (j - i) >= MIN_BLOCK and prof[i:j].sum() >= MIN_INK:
                blocks.append(((i + j) / 2.0, i, j))
            i = j
        else:
            i += 1
    return blocks


def side_points(img, edge, side, corners):
    """
    Return the label centre points on this edge.

    Each point carries `rect` (position along the rectified frame edge, which
    is what the lattice logic works in) and `orig` (the corresponding pixel in
    the original page, which is what becomes a control point). `frame` is the
    span of the neatline itself in the same rectified coordinate, used to
    anchor the label indices.
    """
    h, w = img.shape[:2]
    M, c = rot_matrix(edge, side, w, h)
    warp = cv2.warpAffine(img, M, (w, h), flags=cv2.INTER_CUBIC,
                          borderValue=(255, 255, 255))
    near, far = STRIP[side]
    if side == "top":
        y1, y2 = int(c[1]) - far, int(c[1]) - near
        strip, axis, nearside = warp[max(0, y1):max(1, y2), :], 0, "high"
    elif side == "bottom":
        y1, y2 = int(c[1]) + near, int(c[1]) + far
        strip, axis, nearside = warp[min(h - 1, y1):min(h, y2), :], 0, "low"
    elif side == "left":
        x1, x2 = int(c[0]) - far, int(c[0]) - near
        strip, axis, nearside = warp[:, max(0, x1):max(1, x2)], 1, "high"
    else:
        x1, x2 = int(c[0]) + near, int(c[0]) + far
        strip, axis, nearside = warp[:, min(w - 1, x1):min(w, x2)], 1, "low"

    blocks = find_blocks(strip, axis, nearside)
    Minv = inv_affine(M)
    limit = strip.shape[1] if axis == 0 else strip.shape[0]
    pts = []
    for centre, s, e in blocks:
        # A label running into the edge of the photograph is cut off, so its
        # measured centre is pulled inwards by an unknown amount. Those are
        # flagged and never used as control points.
        clipped = (s <= CLIP_EDGE) or (e >= limit - CLIP_EDGE)
        # the point where this label's graticule line meets the neatline,
        # expressed in the rectified frame, then rotated back
        p = np.array([centre, c[1], 1.0]) if axis == 0 else np.array([c[0], centre, 1.0])
        q = Minv @ p
        crop = (strip[:, max(0, s - 4):e + 4] if axis == 0
                else cv2.rotate(strip[max(0, s - 4):e + 4, :], cv2.ROTATE_90_CLOCKWISE))
        pts.append(dict(orig=[float(q[0]), float(q[1])], rect=float(centre),
                        extent=[int(s), int(e)], clipped=bool(clipped),
                        crop=crop))

    # neatline span along this edge, in the same rectified coordinate
    if side == "top":
        ends = (corners["tl"], corners["tr"])
    elif side == "bottom":
        ends = (corners["bl"], corners["br"])
    elif side == "left":
        ends = (corners["tl"], corners["bl"])
    else:
        ends = (corners["tr"], corners["br"])
    comp = 0 if axis == 0 else 1
    frame = sorted(float((M @ np.array([p[0], p[1], 1.0]))[comp]) for p in ends)
    return pts, frame


def ocr_value(crop, allowed):
    """OCR one label crop and return its value if it is in `allowed`."""
    if crop is None or crop.size == 0:
        return None
    big = cv2.resize(crop, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
    g = cv2.cvtColor(big, cv2.COLOR_BGR2GRAY)
    g = cv2.adaptiveThreshold(g, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                              cv2.THRESH_BINARY, 61, 12)
    g = cv2.copyMakeBorder(g, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=255)
    ok, buf = cv2.imencode(".png", g)
    p = subprocess.run(
        ["tesseract", "stdin", "stdout", "--psm", "7",
         "-c", "tessedit_char_whitelist=0123456789ENSW'\"°"],
        input=buf.tobytes(), capture_output=True)
    val = parse_dms(p.stdout.decode("utf8", "ignore").strip())
    if val is None:
        return None
    near = min(allowed, key=lambda a: abs(a - val))
    return near if abs(near - val) < 1e-6 else None


def line_through(p, q):
    """Homogeneous line through two 2D points."""
    return np.cross([p[0], p[1], 1.0], [q[0], q[1], 1.0])


def cross_point(l1, l2):
    p = np.cross(l1, l2)
    if abs(p[2]) < 1e-12:
        return None
    return [p[0] / p[2], p[1] / p[2]]


# --------------------------------------------------------- lattice assignment
def fit_lattice(centres, n_expected, frame, tol=0.12):
    """
    Work out which printed label each detected block is.

    Two facts make this solvable without reading a single character:

      * the sheet is a plain geographic projection, so a constant step in
        degrees is a constant step in pixels - the label centres lie on a
        regular lattice, which identifies spurious blocks (fitting no node)
        and missing labels (an empty node) unambiguously;

      * all n_expected labels are printed inside the neatline span, so of all
        the ways to slide the lattice along, only one places every label
        inside the frame. That fixes the absolute index without OCR.

    Returns (indices_into_value_list, step_px, keep_mask) over the sorted
    centres, or None.
    """
    c = np.asarray(sorted(centres), float)
    if len(c) < 3:
        return None
    gaps = np.diff(c)
    gaps = gaps[gaps > 1]
    if len(gaps) == 0:
        return None

    lo, hi = frame
    best = None
    cands = sorted({g / k for g in gaps for k in range(1, 4) if g / k > 1})
    for step in cands:
        # The printed graticule fills most of the sheet. Rejecting lattices
        # that cover much less kills the sub-harmonic solutions - a step of
        # half the true one also lands every label on a node, and would
        # otherwise be indistinguishable.
        if (n_expected - 1) * step < 0.70 * (hi - lo):
            continue
        for anchor in range(len(c)):
            # never anchor the phase on a single block: the outermost label is
            # often clipped or merged, which shifts its centre
            idx = (c - c[anchor]) / step
            keep = np.abs(idx - np.round(idx)) < tol
            if keep.sum() < max(3, 0.55 * len(c)):
                continue
            k = np.round(idx).astype(int)
            if k[keep].max() - k[keep].min() > n_expected - 1:
                continue
            a, b = np.polyfit(k[keep], c[keep], 1)   # refit step on kept nodes
            if a <= 1 or (n_expected - 1) * a < 0.70 * (hi - lo):
                continue
            kmin = k[keep].min()
            room = (n_expected - 1) - (k[keep].max() - kmin)
            for o in range(room + 1):
                first = b + (kmin - o) * a       # predicted position of value 0
                last = first + (n_expected - 1) * a
                if first < lo - 0.15 * a or last > hi + 0.15 * a:
                    continue
                resid = float(np.abs(c[keep] - (a * k[keep] + b)).mean())
                slack = min(first - lo, hi - last)
                score = (int(keep.sum()), -slack, -resid)
                if best is None or score > best[0]:
                    best = (score, k - kmin + o, a, keep.copy())
    if best is None:
        return None
    _, values_idx, step, keep = best
    return values_idx, step, keep


# ---------------------------------------------------------------- transform
def page_rotation(edges):
    """Mean tilt of the neatline, in radians."""
    t = [np.arctan(edges["top"]["a"]), np.arctan(edges["bottom"]["a"]),
         -np.arctan(edges["left"]["a"]), -np.arctan(edges["right"]["a"])]
    return float(np.mean(t))


def fit_rectified(constraints, theta, centre):
    """
    Fit pixel -> (lon, lat) for a plain geographic sheet photographed nearly
    flat, and return it as a 2x3 affine.

    Model: undo the page tilt about the image centre, then longitude depends
    only on the rectified x and latitude only on the rectified y.

        lon = a x' + c        lat = b y' + f

    Why not a general affine. Each graticule label pins one coordinate only,
    and on several sides only one of the two opposite margins is legible - the
    page shadow eats the other. The surviving longitude labels then all sit on
    a single line across the sheet, which cannot determine a three-parameter
    row: the cross term is free and the fit extrapolates wildly. Sharing one
    rotation between the two axes removes exactly that freedom, and it is the
    physically right constraint here, because meridians and parallels on this
    projection are orthogonal straight lines.

    Fitted robustly: a label whose block merged with its neighbour has a badly
    biased centre, and must not drag the solution.
    """
    ct, st = np.cos(-theta), np.sin(-theta)
    cx, cy = centre

    def rect(x, y):
        dx, dy = x - cx, y - cy
        return ct * dx - st * dy + cx, st * dx + ct * dy + cy

    params, report = {}, {}
    for axis in (0, 1):
        pts = [(rect(x, y), v) for x, y, ax, v in constraints if ax == axis]
        u = np.array([p[0][axis] for p in pts])
        v = np.array([p[1] for p in pts])
        keep = np.ones(len(u), bool)
        for _ in range(5):
            a, b = np.polyfit(u[keep], v[keep], 1)
            r = np.abs(v - (a * u + b))
            s = 1.4826 * np.median(r[keep]) + 1e-12
            new = r < max(3.0 * s, 0.0015)     # ~165 m floor: a good label
                                               # centre is within a few pixels
            if new.sum() < 2 or (new == keep).all():
                keep = new if new.sum() >= 2 else keep
                break
            keep = new
        a, b = np.polyfit(u[keep], v[keep], 1)
        params[axis] = (a, b)
        report[axis] = (int(keep.sum()), int(len(u)))

    (a, c), (bb, f) = params[0], params[1]
    # compose: rect() is a rotation about (cx, cy), then a scale per axis
    R = np.array([[ct, -st], [st, ct]])
    t = np.array([cx, cy]) - R @ np.array([cx, cy])
    M = np.zeros((2, 3))
    M[0, :2] = a * R[0]
    M[0, 2] = a * t[0] + c
    M[1, :2] = bb * R[1]
    M[1, 2] = bb * t[1] + f
    return M, report


def apply_M(M, x, y):
    return (M[0, 0] * x + M[0, 1] * y + M[0, 2],
            M[1, 0] * x + M[1, 1] * y + M[1, 2])


def invert_affine(M):
    A = np.array([[M[0, 0], M[0, 1]], [M[1, 0], M[1, 1]]])
    t = np.array([M[0, 2], M[1, 2]])
    Ai = np.linalg.inv(A)
    return Ai, -Ai @ t


def main():
    frames = json.loads((OUT / "frames.json").read_text())
    out, problems = {}, []

    for pg, (lons, lats) in SHEETS.items():
        img = cv2.imread(str(SRC / f"page-{pg}.png"), cv2.IMREAD_COLOR)
        fr = frames[pg]
        print(f"\n=== page-{pg} ===  expect {len(lons)} lon, {len(lats)} lat")

        constraints, marks, side_report = [], [], {}
        for side in ("top", "bottom", "left", "right"):
            axis = 0 if side in ("top", "bottom") else 1
            values = lons if axis == 0 else lats
            pts, frame = side_points(img, fr["edges"][side], side, fr["corners"])
            order = sorted(range(len(pts)), key=lambda i: pts[i]["rect"])
            fit = fit_lattice([pts[i]["rect"] for i in order], len(values), frame)
            if fit is None:
                side_report[side] = f"{len(pts)} blocks - no lattice, side dropped"
                print(f"  -- {side:<6} {side_report[side]}")
                continue
            vidx, step, keep = fit

            # Second, tighter pass. The lattice tolerance has to be loose
            # enough to recognise a node at all; but a block whose centre is
            # off by even a few pixels is not fit to be a control point. The
            # usual culprits are the outermost labels, which sit under the
            # sheet title or run into the edge of the photograph and merge
            # with it, shifting their measured centre by tens of pixels.
            cen = np.array([pts[i]["rect"] for i in order])
            if keep.sum() >= 4:
                # Theil-Sen, not least squares. The bad centres here are the
                # two outermost labels, and a least-squares line is dragged by
                # them at both ends at once - which inflates the spread and
                # makes every point look acceptable. The median of pairwise
                # slopes ignores them outright.
                kk, cc = vidx[keep], cen[keep]
                slopes = [(cc[j] - cc[i]) / (kk[j] - kk[i])
                          for i in range(len(kk)) for j in range(i + 1, len(kk))
                          if kk[j] != kk[i]]
                al = float(np.median(slopes))
                bl = float(np.median(cc - al * kk))
                dev = np.abs(cen - (al * vidx + bl))
                keep = keep & (dev < max(12.0, 0.025 * al))

            used, checks = 0, []
            for rank, i in enumerate(order):
                if not keep[rank]:
                    continue
                p = pts[i]
                v = values[vidx[rank]]
                # a clipped label's centre is pulled inwards by an unknown
                # amount, so it identifies its node but must not be a GCP
                if not p["clipped"]:
                    constraints.append((p["orig"][0], p["orig"][1], axis, v))
                    marks.append((p["orig"][0], p["orig"][1], axis))
                    used += 1
                got = ocr_value(p["crop"], values)
                if got is not None:
                    checks.append(got == v)

            agree = f"{sum(checks)}/{len(checks)} OCR agree" if checks else "no OCR check"
            side_report[side] = (f"{used}/{len(values)} labels used "
                                 f"({len(pts)} blocks, 15' = {step:.1f}px, {agree})")
            print(f"  OK {side:<6} {side_report[side]}")
            if checks and not all(checks):
                print(f"     !! OCR disagrees with the lattice on {side}")

        n_lon = sum(1 for c in constraints if c[2] == 0)
        n_lat = sum(1 for c in constraints if c[2] == 1)
        # the model needs 2 points per axis; 3+ gives redundancy, and a sheet
        # running on the bare minimum is flagged so it gets extra scrutiny in
        # the overlay checks later
        if n_lon < 2 or n_lat < 2:
            problems.append((pg, n_lon, n_lat))
            print(f"  !! only {n_lon} lon / {n_lat} lat constraints - cannot fit")
            continue
        if n_lon < 3 or n_lat < 3:
            print(f"  !! LOW REDUNDANCY: {n_lon} lon / {n_lat} lat - "
                  f"no check on this sheet's own control, verify by overlay")

        theta = page_rotation(fr["edges"])
        M, keepstat = fit_rectified(
            constraints, theta, (img.shape[1] / 2.0, img.shape[0] / 2.0))
        print(f"  page tilt {np.degrees(theta):+.3f} deg, "
              f"inliers lon {keepstat[0][0]}/{keepstat[0][1]}, "
              f"lat {keepstat[1][0]}/{keepstat[1][1]}")
        res = []
        for x, y, axis, v in constraints:
            lon, lat = apply_M(M, x, y)
            res.append(((lon if axis == 0 else lat) - v))
        res = np.asarray(res)
        # degrees -> metres (1 deg lat ~ 110.57 km here; lon scaled by cos(lat))
        latc = float(np.mean(lats))
        m_per_deg = np.where(np.array([c[2] for c in constraints]) == 0,
                             111320 * np.cos(np.radians(latc)), 110570)
        res_m = res * m_per_deg

        print(f"  fit from {len(constraints)} constraints "
              f"({n_lon} lon, {n_lat} lat)")
        print(f"    residual  rms = {np.sqrt((res_m**2).mean()):7.1f} m   "
              f"max = {np.abs(res_m).max():7.1f} m")

        # GCP grid at graticule intersections, for gdal
        Ai, ti = invert_affine(M)
        gcps = []
        for L in lons:
            for B in lats:
                px, py = Ai @ np.array([L, B]) + ti
                if -50 <= px <= img.shape[1] + 50 and -50 <= py <= img.shape[0] + 50:
                    gcps.append(dict(px=float(px), py=float(py), lon=L, lat=B))

        out[pg] = dict(size=[img.shape[1], img.shape[0]],
                       affine=M.tolist(), gcps=gcps, lons=lons, lats=lats,
                       corners={k: v for k, v in fr["corners"].items()},
                       residual_rms_m=float(np.sqrt((res_m ** 2).mean())),
                       residual_max_m=float(np.abs(res_m).max()),
                       sides=side_report)
        print(f"  -> {len(gcps)} GCPs on the graticule")

        vis = img.copy()
        for g in gcps:
            cv2.drawMarker(vis, (int(g["px"]), int(g["py"])), (0, 0, 255),
                           cv2.MARKER_CROSS, 46, 4)
        for x, y, axis in marks:
            cv2.circle(vis, (int(x), int(y)), 13,
                       (255, 0, 0) if axis == 0 else (0, 160, 0), -1)
        sc = 1500 / max(vis.shape[:2])
        cv2.imwrite(str(QA / f"gcp_{pg}.jpg"),
                    cv2.resize(vis, None, fx=sc, fy=sc), [cv2.IMWRITE_JPEG_QUALITY, 85])

    (OUT / "gcps.json").write_text(json.dumps(out, indent=2))
    print("\nwrote", OUT / "gcps.json")
    if problems:
        print("\nSHEETS WITHOUT ENOUGH CONSTRAINTS:")
        for pg, a, b in problems:
            print(f"   page-{pg}: {a} lon, {b} lat")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
