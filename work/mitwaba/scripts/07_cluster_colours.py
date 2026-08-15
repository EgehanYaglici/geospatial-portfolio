#!/usr/bin/env python3
"""
Step 7 - Cluster the colours inside each sector sheet and show what came out.

This is the step that needs a cartographer's eye, so it is deliberately split
off: the script does the measuring, a human does the naming. It clusters the
interior colours, then renders every cluster in its own mean colour with an
index printed on it. Reading that image and writing down "cluster 7 is
Kalonga" is the whole manual input for the vectorisation - and because it is
written to a small JSON, the run is reproducible afterwards.

Clusters are formed in CIE Lab, where the perceptual distance between the
tints actually matches how distinguishable they are on the page. Several
clusters routinely belong to the same groupement (the tints sit over a shaded
relief base, so they vary across the sheet), which is why the mapping is
many-to-one.

Output: 03_vector/clusters_<page>.npy, qa/clusters_<page>.jpg
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
VEC.mkdir(exist_ok=True)

SHEETS = ["22", "23", "24"]
K = 20
SAMPLE = 400_000          # pixels used to fit the clusters
MIN_LABEL_PX = 15_000     # only annotate components at least this big


def interior_mask(shape, corners, shrink_px=10):
    h, w = shape
    pts = np.array([corners[k] for k in ("tl", "tr", "br", "bl")], np.float64)
    c = pts.mean(axis=0)
    d = pts - c
    d *= 1 - shrink_px / np.linalg.norm(d, axis=1, keepdims=True)
    m = np.zeros((h, w), np.uint8)
    cv2.fillPoly(m, [(c + d).astype(np.int32)], 1)
    return m


def main():
    frames = json.loads((GEO / "frames.json").read_text())
    rng = np.random.default_rng(0)

    for pg in SHEETS:
        img = cv2.imread(str(SRC / f"page-{pg}.png"))
        h, w = img.shape[:2]
        inside = interior_mask((h, w), frames[pg]["corners"])
        lab = cv2.cvtColor(cv2.bilateralFilter(img, 9, 45, 45), cv2.COLOR_BGR2LAB)

        idx = np.flatnonzero(inside.ravel())
        pick = rng.choice(idx, size=min(SAMPLE, len(idx)), replace=False)
        Z = lab.reshape(-1, 3)[pick].astype(np.float32)
        crit = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.5)
        _, _, centres = cv2.kmeans(Z, K, None, crit, 6, cv2.KMEANS_PP_CENTERS)

        flat = lab.reshape(-1, 3).astype(np.float32)
        d = ((flat[:, None, :] - centres[None, :, :]) ** 2).sum(-1) \
            if False else None
        # chunked nearest-centre to keep memory sane on a 8 Mpx sheet
        cl = np.empty(flat.shape[0], np.int16)
        for s in range(0, flat.shape[0], 1_000_000):
            e = min(s + 1_000_000, flat.shape[0])
            dd = ((flat[s:e, None, :] - centres[None, :, :]) ** 2).sum(-1)
            cl[s:e] = dd.argmin(1)
        cl = cl.reshape(h, w)
        cl[inside == 0] = -1
        np.save(VEC / f"clusters_{pg}.npy", cl)

        # render: each cluster in its own mean BGR, index printed on the
        # largest few components so the mapping can be written by eye
        bgr_c = cv2.cvtColor(centres.reshape(-1, 1, 3).astype(np.uint8),
                             cv2.COLOR_LAB2BGR).reshape(-1, 3)
        vis = np.zeros_like(img)
        for k in range(K):
            vis[cl == k] = bgr_c[k]
        vis[cl < 0] = (255, 255, 255)

        info = []
        for k in range(K):
            m = (cl == k).astype(np.uint8)
            n, lb, st, ce = cv2.connectedComponentsWithStats(m, 8)
            big = [i for i in range(1, n) if st[i, cv2.CC_STAT_AREA] >= MIN_LABEL_PX]
            big.sort(key=lambda i: -st[i, cv2.CC_STAT_AREA])
            for i in big[:3]:
                x, y = int(ce[i][0]), int(ce[i][1])
                cv2.putText(vis, str(k), (x - 22, y + 14),
                            cv2.FONT_HERSHEY_SIMPLEX, 1.6, (0, 0, 0), 7, cv2.LINE_AA)
                cv2.putText(vis, str(k), (x - 22, y + 14),
                            cv2.FONT_HERSHEY_SIMPLEX, 1.6, (255, 255, 255), 2, cv2.LINE_AA)
            info.append(dict(cluster=k, px=int(m.sum()),
                             bgr=[int(v) for v in bgr_c[k]]))

        side = np.hstack([cv2.resize(img, None, fx=0.5, fy=0.5),
                          cv2.resize(vis, None, fx=0.5, fy=0.5)])
        s = 2000 / side.shape[1]
        cv2.imwrite(str(QA / f"clusters_{pg}.jpg"),
                    cv2.resize(side, None, fx=s, fy=s), [cv2.IMWRITE_JPEG_QUALITY, 88])
        (VEC / f"clusters_{pg}.json").write_text(json.dumps(info, indent=2))
        print(f"page-{pg}: {K} clusters over {inside.sum()/1e6:.2f} Mpx "
              f"-> qa/clusters_{pg}.jpg")


if __name__ == "__main__":
    main()
