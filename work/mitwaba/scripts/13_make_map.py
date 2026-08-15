#!/usr/bin/env python3
"""
Step 13 - Draw the A0 map.

Design decisions worth stating:

* Projection is UTM 35S, not lat/lon. A territory 200 km across drawn in plain
  geographic coordinates is visibly sheared at 9 degrees south, and the scale
  bar would be a lie. The graticule is drawn in degrees on top, so the sheet
  still reads in the coordinates the source atlas uses.

* The fill palette encodes the hierarchy instead of decorating it: each
  sector gets a hue, each groupement inside it a shade of that hue. Sector
  membership is then readable without tracing the heavier boundary line, and
  the legend can stay short.

* Three boundary weights only - territoire, sector, groupement - matching the
  three levels in the data. The source atlas uses two and relies on colour for
  the third, which is what makes it hard to read.

Output: 06_output/Mitwaba_A0.pdf and .png
"""
import json
import pathlib
import sys

import geopandas as gpd
import matplotlib as mpl
import numpy as np

mpl.use("Agg")
import matplotlib.patheffects as pe
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Patch, Polygon as MplPolygon
from shapely.geometry import Point, box
import rasterio
from rasterio.plot import plotting_extent

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from gpkg_io import read_gpkg

ROOT = pathlib.Path(__file__).resolve().parents[1]
VEC = ROOT / "03_vector"
CTX = ROOT / "04_context"
OUT = ROOT / "06_output"
OUT.mkdir(exist_ok=True)

UTM = "EPSG:32735"
A0 = (33.11, 46.81)          # inches, portrait
PNG_DPI = 150                # 4966 x 7021 px
MARGIN = 0.055

# one hue family per sector, shades within it per groupement
SECTOR_HUES = {
    "Balomotwa":  ["#e8c39e", "#dcae82", "#cf9866", "#c2834f", "#b06f3d"],
    "Banweshi":   ["#cddca0", "#bccf85", "#a9c26a", "#95b352", "#7fa03e"],
    "Kiona-Ngoy": ["#c9c3de", "#b3aad0", "#9d91c2", "#8678b3", "#6f5fa3"],
}
WATER = "#8fc2dd"
WATER_LINE = "#6ba8ca"
ROAD = {1: ("#b52d1f", 4.2), 2: ("#b52d1f", 3.4), 3: ("#d35400", 2.4),
        4: ("#e08a3c", 1.6), 5: ("#b08a63", 0.9)}
INK = "#1c1c1c"
MUTED = "#5a5248"


def graticule(ax, gdf_wgs, crs, step=0.25):
    """Degree graticule drawn over the projected map."""
    minx, miny, maxx, maxy = gdf_wgs.total_bounds
    lons = np.arange(np.floor(minx / step) * step, maxx + step, step)
    lats = np.arange(np.floor(miny / step) * step, maxy + step, step)
    dense = np.linspace(-0.2, 0.2, 2)
    lines = []
    for lo in lons:
        pts = gpd.GeoSeries(gpd.points_from_xy([lo] * 200,
                                               np.linspace(miny, maxy, 200)),
                            crs=4326).to_crs(crs)
        lines.append(("lon", lo, np.array([[p.x, p.y] for p in pts])))
    for la in lats:
        pts = gpd.GeoSeries(gpd.points_from_xy(np.linspace(minx, maxx, 200),
                                               [la] * 200),
                            crs=4326).to_crs(crs)
        lines.append(("lat", la, np.array([[p.x, p.y] for p in pts])))
    for kind, val, xy in lines:
        ax.plot(xy[:, 0], xy[:, 1], color="#7a7a7a", lw=0.4, ls=(0, (5, 5)),
                zorder=6, alpha=0.55)
    return lines


def dms(val, is_lon):
    hemi = ("E" if val >= 0 else "W") if is_lon else ("N" if val >= 0 else "S")
    v = abs(val)
    d = int(v)
    m = int(round((v - d) * 60))
    if m == 60:
        d, m = d + 1, 0
    return f"{d}°{m:02d}'{hemi}"


def scale_bar(ax, x, y, length_m, height_m, scale_text):
    """
    Alternating bar, drawn on the map in ground units.

    Placed in a corner the territory does not reach, so it sits inside the
    frame - where a scale bar belongs - without covering any of the subject.
    """
    n = 5
    seg = length_m / n
    for i in range(n):
        ax.add_patch(MplPolygon(
            [(x + i * seg, y), (x + (i + 1) * seg, y),
             (x + (i + 1) * seg, y + height_m), (x + i * seg, y + height_m)],
            closed=True, facecolor=INK if i % 2 == 0 else "white",
            edgecolor=INK, lw=1.2, zorder=21))
    for i in range(n + 1):
        ax.text(x + i * seg, y - height_m * 0.7,
                f"{int(i * seg / 1000)}", ha="center", va="top",
                fontsize=13, color=INK, zorder=21)
    ax.text(x + length_m / 2, y + height_m * 1.6, "kilomètres", ha="center",
            va="bottom", fontsize=13, color=INK, zorder=21)
    ax.text(x + length_m / 2, y - height_m * 3.4, scale_text, ha="center",
            va="top", fontsize=12.5, color=MUTED, zorder=21)


def north_arrow(ax, x, y, size):
    ax.add_patch(MplPolygon([(x, y + size), (x - size * 0.30, y - size * 0.55),
                             (x, y - size * 0.22)],
                            closed=True, facecolor=INK, edgecolor=INK,
                            zorder=21))
    ax.add_patch(MplPolygon([(x, y + size), (x + size * 0.30, y - size * 0.55),
                             (x, y - size * 0.22)],
                            closed=True, facecolor="white", edgecolor=INK,
                            lw=1.2, zorder=21))
    ax.text(x, y + size * 1.2, "N", ha="center", va="bottom", fontsize=22,
            weight="bold", color=INK, zorder=21)


def clear_point(poly, avoid, n=45):
    """
    Put a sector label where there is actually room for it.

    Sampling the polygon on a grid and taking the point that maximises the
    distance to the nearest groupement label - and to the polygon's own edge -
    keeps the two label levels from landing on top of each other, which
    happens immediately if both are placed at a representative point.
    """
    minx, miny, maxx, maxy = poly.bounds
    xs = np.linspace(minx, maxx, n)
    ys = np.linspace(miny, maxy, n)
    best, score = poly.representative_point(), -1.0
    for x in xs:
        for y in ys:
            pt = Point(x, y)
            if not poly.contains(pt):
                continue
            d_lab = min((pt.distance(a) for a in avoid), default=1e9)
            s = min(d_lab, poly.boundary.distance(pt) * 1.6)
            if s > score:
                best, score = pt, s
    return best


def main():
    grp = read_gpkg(VEC / "mitwaba.gpkg", "groupements")
    sec = read_gpkg(VEC / "mitwaba.gpkg", "sectors")
    ter = read_gpkg(VEC / "mitwaba.gpkg", "territoire")
    roads = read_gpkg(CTX / "context.gpkg", "roads")
    rivers = read_gpkg(CTX / "context.gpkg", "rivers")
    water = read_gpkg(CTX / "context.gpkg", "water")
    places = read_gpkg(CTX / "context.gpkg", "places")

    grp_w = grp.copy()
    grp, sec, ter, roads, rivers, water, places = [
        d.to_crs(UTM) for d in (grp, sec, ter, roads, rivers, water, places)]

    colour = {}
    for s, shades in SECTOR_HUES.items():
        names = sorted(grp.loc[grp.sector == s, "groupement"])
        for i, n in enumerate(names):
            colour[n] = shades[i % len(shades)]
    grp["fill"] = grp["groupement"].map(colour)

    minx, miny, maxx, maxy = ter.total_bounds
    padx, pady = (maxx - minx) * 0.05, (maxy - miny) * 0.05

    fig = plt.figure(figsize=A0)
    fig.patch.set_facecolor("white")
    ax = fig.add_axes([MARGIN, MARGIN + 0.055, 1 - 2 * MARGIN,
                       1 - 2 * MARGIN - 0.112])
    ax.set_facecolor("#efece6")

    # Terrain first, then the administrative tints over it at partial
    # opacity, so relief reads through the colour instead of replacing it.
    hs_path = CTX / "hillshade_utm35s.tif"
    if hs_path.exists():
        with rasterio.open(hs_path) as src:
            hs = src.read(1)
            # low contrast and low opacity: the relief is there to give the
            # sheet depth, not to compete with the administrative colours
            ax.imshow(hs, extent=plotting_extent(src), cmap="gray",
                      vmin=-140, vmax=300, zorder=1, alpha=0.42,
                      interpolation="bilinear")

    graticule(ax, grp_w, UTM)

    grp.plot(ax=ax, color=grp["fill"], edgecolor="none", zorder=2, alpha=0.74)
    water.plot(ax=ax, color=WATER, edgecolor=WATER_LINE, lw=0.4, zorder=3)

    minor = rivers[rivers.waterway == "stream"]
    major = rivers[rivers.waterway == "river"]
    minor.plot(ax=ax, color=WATER_LINE, lw=0.55, alpha=0.85, zorder=3.2)
    major.plot(ax=ax, color="#4f93b8", lw=1.7, zorder=3.3)

    for cls in sorted(roads.cls.unique(), reverse=True):
        col, lw = ROAD[int(cls)]
        sub = roads[roads.cls == cls]
        sub.plot(ax=ax, color="white", lw=lw + 1.4, zorder=4, capstyle="round")
        sub.plot(ax=ax, color=col, lw=lw, zorder=4.1, capstyle="round")

    # Fade everything outside the territory. Without it the surrounding
    # relief reads as loudly as the subject and the sheet has no focus.
    veil = box(minx - padx * 3, miny - pady * 3,
               maxx + padx * 3, maxy + pady * 3).difference(
                   ter.geometry.iloc[0])
    gpd.GeoSeries([veil], crs=ter.crs).plot(ax=ax, color="white", alpha=0.62,
                                            edgecolor="none", zorder=4.6)

    grp.boundary.plot(ax=ax, color="#5a5248", lw=0.9, zorder=5)
    sec.boundary.plot(ax=ax, color=INK, lw=2.2, zorder=5.2)
    ter.boundary.plot(ax=ax, color=INK, lw=4.0, zorder=5.3)

    # ---- labels
    grp_pts = [r.geometry.representative_point() for _, r in grp.iterrows()]
    for _, r in grp.iterrows():
        p = r.geometry.representative_point()
        ax.text(p.x, p.y, r.groupement.upper(), ha="center", va="center",
                fontsize=19, color="#332c24", zorder=8,
                path_effects=[pe.withStroke(linewidth=6, foreground="white")])
    for _, r in sec.iterrows():
        p = clear_point(r.geometry, grp_pts)
        ax.text(p.x, p.y, f"{r.sector_type.upper()}  DE  {r['sector'].upper()}",
                ha="center", va="center", fontsize=27, weight="bold",
                color="#241f19", zorder=9, alpha=0.9,
                path_effects=[pe.withStroke(linewidth=6, foreground="white")])

    # The brief asks for rivers and streams "including their names", so the
    # named watercourses are labelled, not just drawn. One label per name -
    # OSM splits a river into many ways and labelling each would repeat the
    # same word a dozen times down one valley - and the longest way is the one
    # that gets it, since that is where there is room to write it.
    named_rivers = rivers[rivers["name"].notna()].copy()
    named_rivers["len"] = named_rivers.length
    named_rivers = (named_rivers.sort_values("len", ascending=False)
                    .drop_duplicates("name"))
    named_rivers = named_rivers[named_rivers["len"] > 6000].head(22)
    for _, r in named_rivers.iterrows():
        line = r.geometry
        if line.geom_type == "MultiLineString":
            line = max(line.geoms, key=lambda g: g.length)
        pt = line.interpolate(0.55, normalized=True)
        a = line.interpolate(0.50, normalized=True)
        b = line.interpolate(0.60, normalized=True)
        ang = np.degrees(np.arctan2(b.y - a.y, b.x - a.x))
        if ang > 90:
            ang -= 180
        if ang < -90:
            ang += 180
        ax.text(pt.x, pt.y, r["name"], fontsize=10.5, style="italic",
                color="#2c6588", ha="center", va="center", rotation=ang,
                rotation_mode="anchor", zorder=7,
                path_effects=[pe.withStroke(linewidth=3, foreground="white")])

    # Road numbers, as on the client's reference sheet. Placed on the road
    # rather than beside it, in a small plate, which is how a road map does it.
    for _, r in roads[roads["ref"].notna()].iterrows():
        g = r.geometry
        parts = list(g.geoms) if g.geom_type == "MultiLineString" else [g]
        # OSM splits a route into many ways, so labelling only the longest one
        # puts a single RP617 plate on a 260 km road. Every substantial part
        # gets one, which is how the number repeats along a road map.
        placed = []
        for part in sorted(parts, key=lambda x: -x.length):
            if part.length < 15000 or len(placed) >= 5:
                continue
            pt = part.interpolate(0.5, normalized=True)
            if any(pt.distance(q) < 28000 for q in placed):
                continue
            placed.append(pt)
            ax.text(pt.x, pt.y, r["ref"], fontsize=10.5, weight="bold",
                    color="#8c2016", ha="center", va="center", zorder=12,
                    bbox=dict(boxstyle="round,pad=0.30", facecolor="white",
                              edgecolor="#8c2016", linewidth=1.2, alpha=0.96))

    for _, r in places.iterrows():
        big = r.label_class == "town"
        ax.plot(r.geometry.x, r.geometry.y, "o", ms=7 if big else 4.5,
                mfc="white" if big else "#3a332b", mec=INK,
                mew=1.4 if big else 0.9, zorder=10)
        ax.text(r.geometry.x + 1800, r.geometry.y + 1200, r["name"],
                fontsize=14 if big else 11.5,
                style="normal" if big else "italic",
                weight="bold" if big else "normal", color="#17140f", zorder=11,
                path_effects=[pe.withStroke(linewidth=3.2, foreground="white")])

    # ---- graticule edge labels
    step = 0.25
    bx0, by0, bx1, by1 = grp_w.total_bounds
    for lo in np.arange(np.floor(bx0 / step) * step, bx1 + step, step):
        p = gpd.GeoSeries(gpd.points_from_xy([lo], [by0]), crs=4326).to_crs(UTM)[0]
        if minx - padx < p.x < maxx + padx:
            ax.annotate(dms(lo, True), (p.x, miny - pady), ha="center", va="top",
                        fontsize=11, color="#3a332b", annotation_clip=False)
    for la in np.arange(np.floor(by0 / step) * step, by1 + step, step):
        p = gpd.GeoSeries(gpd.points_from_xy([bx0], [la]), crs=4326).to_crs(UTM)[0]
        if miny - pady < p.y < maxy + pady:
            ax.annotate(dms(la, False), (minx - padx, p.y), ha="right",
                        va="center", fontsize=11, color="#3a332b",
                        annotation_clip=False)

    ax.set_xlim(minx - padx, maxx + padx)
    ax.set_ylim(miny - pady, maxy + pady)

    # Furniture is placed by asking where there is room, not by hard-coding a
    # corner. Candidate corners are tried in order of preference and the first
    # one whose footprint clears the territory wins, so the map is never
    # covered - and the same code still works for the next territory, whose
    # shape will sit differently in the frame.
    X0, X1 = minx - padx, maxx + padx
    Y0, Y1 = miny - pady, maxy + pady
    W, H = X1 - X0, Y1 - Y0
    land = ter.geometry.iloc[0]

    def overlap(x0, y0, x1, y1, pad=0.012):
        b = box(x0 - pad * W, y0 - pad * H, x1 + pad * W, y1 + pad * H)
        return land.intersection(b).area

    def place(candidates, footprint):
        """Least-obstructive of the candidate positions, with its overlap."""
        scored = [(overlap(*footprint(c)), c) for c in candidates]
        scored.sort(key=lambda t: t[0])
        return scored[0][1], scored[0][0]

    def panel(x0, y0, x1, y1, pad=0.014):
        """White backing, so furniture stays legible if it must sit on land."""
        ax.add_patch(MplPolygon(
            [(x0 - pad * W, y0 - pad * H), (x1 + pad * W, y0 - pad * H),
             (x1 + pad * W, y1 + pad * H), (x0 - pad * W, y1 + pad * H)],
            closed=True, facecolor="white", alpha=0.86, edgecolor=INK,
            lw=1.0, zorder=20))

    arrow_h = 0.030 * H
    a_foot = lambda c: (X0 + c[0] * W - arrow_h, Y0 + c[1] * H - arrow_h,
                        X0 + c[0] * W + arrow_h,
                        Y0 + c[1] * H + arrow_h * 2.4)
    (acx, acy), a_ov = place([(0.055, 0.885), (0.945, 0.885), (0.055, 0.115),
                              (0.945, 0.115)], a_foot)
    if a_ov > 0:
        panel(*a_foot((acx, acy)))
    north_arrow(ax, X0 + acx * W, Y0 + acy * H, arrow_h)

    sheet_scale = W / (A0[0] * (1 - 2 * MARGIN) * 0.0254)
    scale_txt = f"1 : {round(sheet_scale / 1000) * 1000:,}".replace(",", " ")
    bar_len, bar_h = 50000.0, 0.008 * H
    b_foot = lambda c: (X0 + c[0] * W - (bar_len if c[0] > 0.5 else 0),
                        Y0 + c[1] * H - bar_h * 4.4,
                        X0 + c[0] * W - (bar_len if c[0] > 0.5 else 0) + bar_len,
                        Y0 + c[1] * H + bar_h * 3.2)
    # The lower left is not a candidate: that corner is the legend's. Ordered
    # right to left, top last, so the bar lands in the emptiest free corner.
    bc, b_ov = place([(0.985, 0.060), (0.985, 0.135), (0.985, 0.93)], b_foot)
    if b_ov > 0:
        panel(*b_foot(bc))
    scale_bar(ax, X0 + bc[0] * W - (bar_len if bc[0] > 0.5 else 0),
              Y0 + bc[1] * H, bar_len, bar_h, scale_txt)
    ax.set_xticks([])
    ax.set_yticks([])
    for sp in ax.spines.values():
        sp.set_linewidth(1.6)
        sp.set_edgecolor(INK)


    # ---- title block
    fig.text(MARGIN, 1 - MARGIN + 0.012,
             "RÉPUBLIQUE DÉMOCRATIQUE DU CONGO  ·  PROVINCE DU HAUT-KATANGA",
             fontsize=19, color="#5a5248", va="bottom")
    fig.text(MARGIN, 1 - MARGIN - 0.020, "TERRITOIRE DE MITWABA",
             fontsize=52, weight="bold", color=INK, va="bottom")
    fig.text(MARGIN, 1 - MARGIN - 0.036,
             "Limites administratives : secteurs, chefferie et groupements",
             fontsize=21, color="#3a332b", va="bottom")

    # ---- legend
    handles = [Patch(facecolor="none", edgecolor=INK, lw=4.0,
                     label="Limite de territoire"),
               Patch(facecolor="none", edgecolor=INK, lw=2.2,
                     label="Limite de secteur / chefferie"),
               Patch(facecolor="none", edgecolor="#5a5248", lw=0.9,
                     label="Limite de groupement")]
    for s, shades in SECTOR_HUES.items():
        t = sec.loc[sec.sector == s, "sector_type"].iloc[0]
        handles.append(Patch(facecolor=shades[2], edgecolor="#5a5248",
                             label=f"{t} de {s}"))
    handles += [
        Line2D([], [], color=ROAD[1][0], lw=3.4, label="Route principale"),
        Line2D([], [], color=ROAD[3][0], lw=2.0, label="Route secondaire"),
        Line2D([], [], color=ROAD[5][0], lw=0.9, label="Piste"),
        Line2D([], [], color=WATER_LINE, lw=1.1, label="Cours d'eau"),
        Patch(facecolor=WATER, edgecolor=WATER_LINE, label="Lac, étendue d'eau"),
        Line2D([], [], color=INK, marker="o", ls="", mfc="white", ms=7,
               label="Ville"),
        Line2D([], [], color=INK, marker="o", ls="", mfc="#3a332b", ms=4.5,
               label="Localité"),
    ]
    leg = fig.legend(handles=handles, loc="lower left",
                     bbox_to_anchor=(MARGIN + 0.018, MARGIN + 0.075), ncol=2,
                     fontsize=15, frameon=True, title="LÉGENDE",
                     title_fontsize=17, borderpad=1.1, labelspacing=0.9,
                     handlelength=2.6, columnspacing=2.4)
    leg.get_frame().set_facecolor('white')
    leg.get_frame().set_alpha(0.94)
    leg.get_frame().set_edgecolor(INK)
    leg.get_frame().set_linewidth(1.2)
    leg.get_title().set_fontweight("bold")

    stats = (f"{len(ter)} territoire · {len(sec)} secteurs/chefferie · "
             f"{len(grp)} groupements · {grp.area.sum()/1e6:,.0f} km²")
    src = (
        "Limites administratives : CENI / RD Congo, Atlas électoral, août 2016 "
        "(Territoire de Mitwaba, pl. 54–56) — reportées par géoréférencement "
        "et vectorisation.\n"
        "Routes, hydrographie et localités : OpenStreetMap (© contributeurs "
        "OSM, ODbL), extraction 2026.\n"
        "Projection UTM zone 35S (EPSG:32735) · Datum WGS 84 · "
        "Graticule en degrés géographiques.\n"
        "Les limites reproduisent l'atlas CENI 2016 ; leur précision de "
        "report est de l'ordre de 200 à 800 m. Voir la note d'incertitude "
        "jointe."
    )
    fig.text(1 - MARGIN, MARGIN * 0.40 + 0.030, stats, ha="right", va="bottom",
             fontsize=15, color="#3a332b")
    fig.text(1 - MARGIN, MARGIN * 0.40 - 0.014, src, ha="right", va="bottom",
             fontsize=11.5, color="#5a5248", linespacing=1.6)

    pdf = OUT / "Mitwaba_A0.pdf"
    png = OUT / "Mitwaba_A0.png"
    fig.savefig(pdf, format="pdf")
    fig.savefig(png, format="png", dpi=PNG_DPI)
    plt.close(fig)

    jpg = OUT / "Mitwaba_A0.jpg"
    from PIL import Image
    Image.MAX_IMAGE_PIXELS = None
    Image.open(png).convert("RGB").save(jpg, quality=92, optimize=True)

    print(f"wrote {pdf}")
    print(f"wrote {png}  ({A0[0]*PNG_DPI:.0f} x {A0[1]*PNG_DPI:.0f} px)")
    print(f"wrote {jpg}")


if __name__ == "__main__":
    main()
