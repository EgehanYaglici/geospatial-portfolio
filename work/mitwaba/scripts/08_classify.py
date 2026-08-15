#!/usr/bin/env python3
"""
Step 8 - Classify every map pixel into its groupement.

Seeded classification rather than blind clustering. Global k-means separates
the strong tints happily but loses the weak ones: on the Balomotwa sheet the
Musabila tint is a pale mauve only a few Lab units from the blue-grey used for
neighbouring territories, and clustering merges the two. A seed taken from
inside each groupement pins the tint that actually matters, and the same seed
list documents exactly what was assumed.

Seeds were read off the sheets themselves and are listed below with the colour
found there, so any of them can be re-checked against the source image.

The output is built to be topologically clean by construction:

  * classify -> keep only pixels that landed on a groupement tint,
  * close, take the largest connected component, fill its holes: that is the
    sector body, and it swallows the roads, rivers, village dots, place names
    and callout boxes printed over the tints,
  * assign every pixel of the body to its nearest classified pixel.

Every pixel of the sector therefore carries exactly one groupement, so
polygonising cannot leave a sliver gap or an overlap along a shared boundary.

Output: 03_vector/labels_<page>.npy + qa/labels_<page>.jpg
"""
import json
import pathlib

import cv2
import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "01_source"
GEO = ROOT / "02_georef"
VEC = ROOT / "03_vector"
QA = ROOT / "qa"

# seed pixel per groupement, with the median RGB measured in a 29x29 window
SEEDS = {
    "22": {                                    # Secteur de Balomotwa
        "Mukana":   (1250, 850),               # 208,143,142  salmon
        "Kalonga":  (1722, 688),               # 192,194,121  olive
        "Muombe":   (2150, 620),               # 175, 58,113  magenta
        "Musabila": (1130, 1270),              # 200,185,213  pale mauve
        "Mufunga":  (1850, 2000),              # 222,195,150  orange tan
    },
    "23": {                                    # Secteur de Banweshi
        "Tomombo":  (688, 961),                # 208,197, 88  yellow
        "Kanfwa":   (716, 1440),               # 179,102,161  pink magenta
        "Kitobo":   (1350, 1250),              # 204,151,133  salmon
        "Kalera":   (1491, 825),               # 218,191,128  tan
        "Sambwe":   (2050, 1413),              # 184,204,148  yellow green
    },
    "24": {                                    # Chefferie de Kiona-Ngoy
        "Mwema":    (1250, 1050),              # 212,141,142  salmon
        "Kintya":   (784, 1387),               # 188,198,124  yellow green
        "Kabanda":  (1433, 1798),              # 225,215, 85  bright yellow
        "Katolo":   (2117, 1162),              # 205,183,140  tan
    },
}

# Ground that is NOT part of the sector is identified by chroma, not by hand
# picked samples. Measured on all three sheets: every groupement tint sits at
# chroma 15 or above (palest is Katolo at 15.1 and Musabila at 16.3), while
# the paper, the grey used for neighbouring territories and the park hatching
# all sit at 12 or below. Hand-picked background samples were worse than this
# in practice - one of them landed inside the Mwema enlargement box on the
# Kiona-Ngoy sheet, taught the classifier that salmon was background, and
# wiped out two groupements.
CHROMA_MIN = 13.0

# fixed ink / overprint colours, given as RGB. Anything landing on these is
# treated as "covered", not as a groupement, and gets filled in from around it.
OVERPRINT_RGB = [
    (20, 20, 20),      # black line work and place names
    (90, 90, 90),      # grey text at small sizes
    (245, 245, 245),   # paper white, callout boxes, legend panels
    (150, 30, 50),     # main road red
    (205, 70, 90),     # secondary road red
    (150, 200, 225),   # watercourse blue
]

L_WEIGHT = 0.35      # lightness counts this much next to a and b
MAX_DE = 42          # chroma-weighted Lab distance beyond which a pixel is
                     # not considered to be that tint at all. Loose, because
                     # CHROMA_MIN already excludes everything untinted; this
                     # only catches strongly off-palette ink.
SEED_CLOSE = 41      # closing applied before the seed-connectivity test. It has
                     # to be wider than the widest thing printed across a
                     # groupement - the main road plus its casing, and the
                     # inscription-centre callout boxes - otherwise a
                     # groupement is cut in two and only the half holding the
                     # seed survives.
CLOSE_R = 11          # bridges roads and text lines drawn over a tint
MIN_ISLAND_PX = 2500  # specks smaller than this are absorbed by their neighbour
OVERPRINT_R = 9       # scale of the printed overprint marks
OVERPRINT_DE = 16     # how much darker than its surroundings a mark must be
REFINE_ITERS = 4      # seed re-estimation passes


def find_boxes(gray, inside):
    """
    Locate the panels printed on top of the map: legend, statistics, locator
    and the enlargement insets.

    They matter because an enlargement inset is filled with the SAME tint as
    the groupement it enlarges - the Mwema box on the Kiona-Ngoy sheet is
    Mwema salmon, the Mufunga box on Balomotwa is Mufunga orange - so a colour
    classifier reads them as a second, detached copy of that groupement
    sitting in the middle of somebody else's ground.

    A panel is a thin dark rectangle, so it shows up as long straight ink in
    both directions; closing that outline and asking whether it fills out to a
    solid rectangle separates panels from the map's own line work.
    """
    from scipy.ndimage import binary_fill_holes
    h, w = gray.shape
    fg = cv2.GaussianBlur(gray, (0, 0), 2)
    bg = cv2.GaussianBlur(gray, (0, 0), 61)
    ink = (((bg.astype(np.int16) - fg.astype(np.int16)) > 20) & (inside > 0)).astype(np.uint8)
    hk = cv2.getStructuringElement(cv2.MORPH_RECT, (int(w * 0.040), 1))
    vk = cv2.getStructuringElement(cv2.MORPH_RECT, (1, int(h * 0.040)))
    lines = (cv2.dilate(cv2.morphologyEx(ink, cv2.MORPH_OPEN, hk), np.ones((3, 3), np.uint8)) |
             cv2.dilate(cv2.morphologyEx(ink, cv2.MORPH_OPEN, vk), np.ones((3, 3), np.uint8)))
    closed = cv2.morphologyEx(lines, cv2.MORPH_CLOSE,
                              cv2.getStructuringElement(cv2.MORPH_RECT, (31, 31)))
    n, lab, stats, _ = cv2.connectedComponentsWithStats(closed, 8)
    boxes = []
    for i in range(1, n):
        x, y, bw, bh, _ = stats[i]
        if bw < w * 0.055 or bh < h * 0.035 or bw * bh > 0.45 * w * h:
            continue
        if binary_fill_holes(lab[y:y + bh, x:x + bw] == i).sum() < 0.55 * bw * bh:
            continue
        boxes.append((int(x), int(y), int(bw), int(bh)))
    return boxes


def interior_mask(shape, corners, shrink_px=12):
    h, w = shape
    pts = np.array([corners[k] for k in ("tl", "tr", "br", "bl")], np.float64)
    c = pts.mean(axis=0)
    d = pts - c
    d *= 1 - shrink_px / np.linalg.norm(d, axis=1, keepdims=True)
    m = np.zeros((h, w), np.uint8)
    cv2.fillPoly(m, [(c + d).astype(np.int32)], 1)
    return m


def rgb_to_lab(rgb):
    px = np.array([[list(rgb)[::-1]]], np.uint8)     # RGB -> BGR
    return cv2.cvtColor(px, cv2.COLOR_BGR2LAB)[0, 0].astype(np.float32)


def seed_lab(img_lab, x, y, r=14):
    win = img_lab[y - r:y + r + 1, x - r:x + r + 1].reshape(-1, 3)
    return np.median(win, axis=0).astype(np.float32)


def largest_component(mask):
    n, lab, stats, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), 8)
    if n <= 1:
        return mask.astype(bool)
    k = 1 + np.argmax(stats[1:, cv2.CC_STAT_AREA])
    return lab == k


def fill_holes(mask):
    m = mask.astype(np.uint8)
    ff = np.zeros((m.shape[0] + 2, m.shape[1] + 2), np.uint8)
    inv = (1 - m).copy()
    cv2.floodFill(inv, ff, (0, 0), 2)
    return (m > 0) | (inv != 2)


def nearest_fill(classes, known, region):
    """Give every pixel of `region` the class of its nearest known pixel."""
    unknown = (region & ~known).astype(np.uint8)
    _, lbl = cv2.distanceTransformWithLabels(
        unknown, cv2.DIST_L2, 3, labelType=cv2.DIST_LABEL_PIXEL)
    flat_known = np.flatnonzero(known.ravel())
    lut = np.zeros(int(lbl.max()) + 1, np.int32)
    lut[lbl.ravel()[flat_known]] = classes.ravel()[flat_known]
    out = np.where(known, classes, lut[lbl])
    out[~region] = 0
    return out


def absorb_islands(labels, region, min_px):
    """Remove specks: any component below min_px is redone from its neighbours."""
    out = labels.copy()
    for cls in np.unique(labels[labels > 0]):
        m = (out == cls).astype(np.uint8)
        n, lab, stats, _ = cv2.connectedComponentsWithStats(m, 8)
        if n <= 1:
            continue
        keep = 1 + np.argmax(stats[1:, cv2.CC_STAT_AREA])
        for i in range(1, n):
            if i != keep and stats[i, cv2.CC_STAT_AREA] < min_px:
                out[lab == i] = 0
    known = out > 0
    return nearest_fill(out, known, region)


def nearest_centre(flat, C):
    """
    argmin over centres of the squared Lab distance, via one matrix product.

    Expanding ||x - c||^2 to ||x||^2 - 2 x.c + ||c||^2 lets the whole thing be
    a single GEMM instead of materialising an (Npixels x Ncentres x 3) array.
    On an 8 megapixel sheet that is the difference between seconds and minutes.
    """
    cc = (C ** 2).sum(1)
    out = np.empty(flat.shape[0], np.int16)
    for s in range(0, flat.shape[0], 2_000_000):
        e = min(s + 2_000_000, flat.shape[0])
        d = cc[None, :] - 2.0 * (flat[s:e] @ C.T)
        out[s:e] = d.argmin(1)
    return out


def main():
    import sys
    frames = json.loads((GEO / "frames.json").read_text())
    only = sys.argv[1:] or list(SEEDS)
    mpath = VEC / "labels_manifest.json"
    manifest = json.loads(mpath.read_text()) if mpath.exists() else {}

    for pg, seeds in SEEDS.items():
        if pg not in only:
            continue
        img = cv2.imread(str(SRC / f"page-{pg}.png"))
        h, w = img.shape[:2]
        # Find the thin dark overprint - park hatching, place names,
        # watercourses, minor roads - and refuse to read colour there, rather
        # than trying to paint over it. A greyscale closing does erase those
        # marks, but closing is a local maximum: over hatching it also lifts
        # the tint itself several units brighter, which was enough to push the
        # Kintya yellow-green up into the Kabanda yellow and shred the
        # boundary between them. Comparing the sheet against its own closing
        # locates the same marks without touching the colours that remain.
        kink = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (OVERPRINT_R, OVERPRINT_R))
        g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        overprint = (cv2.morphologyEx(g, cv2.MORPH_CLOSE, kink).astype(np.int16)
                     - g.astype(np.int16)) > OVERPRINT_DE
        overprint = cv2.dilate(overprint.astype(np.uint8),
                               np.ones((3, 3), np.uint8)).astype(bool)
        lab = cv2.cvtColor(cv2.medianBlur(img, 5), cv2.COLOR_BGR2LAB)
        inside = interior_mask((h, w), frames[pg]["corners"]).astype(bool)

        boxes = find_boxes(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), inside.astype(np.uint8))
        for bx, by, bw_, bh_ in boxes:
            inside[max(0, by - 3):by + bh_ + 3, max(0, bx - 3):bx + bw_ + 3] = False
        print(f"page-{pg}: {len(boxes)} printed panels masked out")

        names = list(seeds)
        chroma = np.hypot(lab[:, :, 1].astype(np.float32) - 128.0,
                          lab[:, :, 2].astype(np.float32) - 128.0)
        # Membership of the sector and the choice of groupement are two
        # different questions. A hatched reserve is still tinted between the
        # hatch strokes, so it belongs to the sector; but its individual
        # pixels are unreliable, so they should not vote on which groupement
        # it is. `tinted` answers the first question, `confident` the second.
        tinted = inside & (chroma >= CHROMA_MIN)

        W = np.array([L_WEIGHT, 1.0, 1.0], np.float32)
        flat = lab.reshape(-1, 3).astype(np.float32)
        ink = np.stack([rgb_to_lab(c) for c in OVERPRINT_RGB])
        C = np.stack([seed_lab(lab, *seeds[nm]) for nm in names])

        # Refine the seeds against the sheet instead of trusting the single
        # spot they were sampled from.
        #
        # A hand-placed seed is one 29x29 window, and where two tints are
        # close that is not enough. The Kintya sample happened to land on a
        # slightly washed-out patch, which put it 22 Lab units from a typical
        # Kintya pixel and 20 from a typical Kabanda one - so the two
        # groupements came out interleaved pixel by pixel across a boundary
        # that is perfectly clear to the eye. Re-estimating each centre as the
        # median of the pixels currently assigned to it fixes that in one or
        # two passes, while the seed still decides WHICH region is which.
        for it in range(REFINE_ITERS):
            Cw = np.vstack([C, ink]) * W
            best = nearest_centre(flat * W, Cw).reshape(h, w)
            dist = np.sqrt(((flat * W - Cw[best.ravel()]) ** 2).sum(1)).reshape(h, w)

            cls = np.zeros((h, w), np.int32)
            for i, nm in enumerate(names):
                cls[(best == i) & tinted & ~overprint & (dist < MAX_DE)] = i + 1

            # Keep, for each groupement, only the blob its own seed sits in.
            # Nearest-seed alone is not enough: the park hatching north-west of
            # Balomotwa averages to a faintly warm grey that lands nearer the
            # Mukana salmon than anything else, and a patch of it two sheets
            # away from Mukana was being claimed as Mukana. A groupement is one
            # contiguous area on these sheets, so anything unreachable from the
            # seed is a look-alike, not the thing itself.
            kseed = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (SEED_CLOSE, SEED_CLOSE))
            for i, nm in enumerate(names):
                m = cv2.morphologyEx((cls == i + 1).astype(np.uint8), cv2.MORPH_CLOSE, kseed)
                n, comp, stats, _ = cv2.connectedComponentsWithStats(m, 8)
                sx, sy = seeds[nm]
                want = comp[sy, sx]
                if want == 0:                    # seed fell on an overprint pixel
                    ys, xs = np.nonzero(m)
                    if len(xs) == 0:
                        continue
                    d2 = (xs - sx) ** 2 + (ys - sy) ** 2
                    want = comp[ys[d2.argmin()], xs[d2.argmin()]]
                cls[(cls == i + 1) & (comp != want)] = 0

            if it < REFINE_ITERS - 1:
                moved = 0.0
                for i, nm in enumerate(names):
                    sel = cls == i + 1
                    if sel.sum() < 5000:
                        continue
                    new_c = np.median(lab[sel].astype(np.float32), axis=0)
                    moved = max(moved, float(np.abs(new_c - C[i]).max()))
                    C[i] = new_c
                if moved < 0.5:
                    break

        # Grow the sector body out from the confident pixels through the rest
        # of the tinted area. Building the body from the confident pixels
        # alone loses the hatched reserves: their tint is real and they are
        # part of the groupement, but nearly every pixel in them is overprint
        # and so was excluded from voting. Reconstruction keeps exactly the
        # tinted regions that a confident pixel can reach.
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (CLOSE_R, CLOSE_R))
        reach = cv2.morphologyEx(tinted.astype(np.uint8), cv2.MORPH_CLOSE, k)
        n, comp, _, _ = cv2.connectedComponentsWithStats(reach, 8)
        hit = np.zeros(n, bool)
        hit[np.unique(comp[cls > 0])] = True
        hit[0] = False
        body = hit[comp]
        # Union of the seed-connected parts, not the single largest blob. A
        # sector is contiguous on the ground, but on the sheet its parts can be
        # separated by a river or a road drawn right along the boundary, and
        # keeping only the biggest blob silently dropped whole groupements.
        body = fill_holes(body) & inside

        confident = (cls > 0) & body & ~overprint
        if confident.sum() < 1000:                 # nothing left to vote with
            confident = (cls > 0) & body
        labels = nearest_fill(cls, confident, body)
        labels = absorb_islands(labels, body, MIN_ISLAND_PX)

        np.save(VEC / f"labels_{pg}.npy", labels.astype(np.uint8))
        manifest[pg] = dict(names=names, seeds={n: list(seeds[n]) for n in names})
        mpath.write_text(json.dumps(manifest, indent=2))

        palette = np.array([[255, 255, 255], [120, 140, 240], [90, 200, 220],
                            [200, 90, 200], [120, 220, 140], [240, 170, 90],
                            [90, 120, 230]], np.uint8)
        vis = palette[np.clip(labels, 0, len(palette) - 1)]
        edge = cv2.morphologyEx(labels.astype(np.uint8), cv2.MORPH_GRADIENT,
                                np.ones((3, 3), np.uint8)) > 0
        vis[edge] = (0, 0, 0)
        blend = cv2.addWeighted(img, 0.45, vis, 0.55, 0)
        for i, nm in enumerate(names):
            m = labels == i + 1
            if m.sum() == 0:
                continue
            ys, xs = np.nonzero(m)
            cv2.putText(blend, f"{nm} {m.sum()/1e6:.2f}Mpx",
                        (int(xs.mean()) - 120, int(ys.mean())),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.1, (0, 0, 0), 6, cv2.LINE_AA)
            cv2.putText(blend, f"{nm} {m.sum()/1e6:.2f}Mpx",
                        (int(xs.mean()) - 120, int(ys.mean())),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.1, (255, 255, 255), 2, cv2.LINE_AA)
        s = 1600 / max(h, w)
        cv2.imwrite(str(QA / f"labels_{pg}.jpg"), cv2.resize(blend, None, fx=s, fy=s),
                    [cv2.IMWRITE_JPEG_QUALITY, 88])

        areas = {nm: int((labels == i + 1).sum()) for i, nm in enumerate(names)}
        print(f"page-{pg}: body {body.sum()/1e6:.2f} Mpx")
        for nm, a in areas.items():
            print(f"    {nm:<10} {a/1e6:6.3f} Mpx  ({100*a/max(1,body.sum()):5.1f}%)")

    mpath.write_text(json.dumps(manifest, indent=2))
    print("\nwrote label rasters to", VEC)


if __name__ == "__main__":
    main()
