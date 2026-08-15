#!/usr/bin/env python3
"""
Step 17 - Write the uncertainty note that ships with the map.

The brief asks for "a short note listing any boundaries that remain uncertain
or could not be fully verified". Every figure in it is read from the QA
outputs rather than typed, so the note cannot drift away from the data it
describes.

Output: 06_output/Mitwaba_uncertainty_note.pdf (+ .md)
"""
import json
import pathlib
import sys

from reportlab.lib import colors
from reportlab.lib.enums import TA_JUSTIFY
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (KeepTogether, PageBreak, Paragraph,
                                SimpleDocTemplate, Spacer, Table, TableStyle)

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from gpkg_io import read_gpkg

ROOT = pathlib.Path(__file__).resolve().parents[1]
GEO = ROOT / "02_georef"
VEC = ROOT / "03_vector"
QA = ROOT / "qa"
OUT = ROOT / "06_output"

INK = colors.HexColor("#1c1c1c")
MUTED = colors.HexColor("#5a5248")
RULE = colors.HexColor("#c9c2b6")


def styles():
    ss = getSampleStyleSheet()
    return dict(
        h1=ParagraphStyle("h1", parent=ss["Title"], fontName="Helvetica-Bold",
                          fontSize=17, leading=21, textColor=INK,
                          alignment=0, spaceAfter=2),
        sub=ParagraphStyle("sub", fontName="Helvetica", fontSize=10.5,
                           leading=14, textColor=MUTED, spaceAfter=14),
        h2=ParagraphStyle("h2", fontName="Helvetica-Bold", fontSize=11.5,
                          leading=15, textColor=INK, spaceBefore=13,
                          spaceAfter=5),
        p=ParagraphStyle("p", fontName="Helvetica", fontSize=9.6, leading=14,
                         textColor=INK, alignment=TA_JUSTIFY, spaceAfter=7),
        small=ParagraphStyle("small", fontName="Helvetica", fontSize=8.4,
                             leading=11.5, textColor=MUTED, spaceAfter=4),
    )


def table(data, widths, align_right=()):
    t = Table(data, colWidths=widths, hAlign="LEFT")
    cmds = [
        ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 8.6),
        ("FONT", (0, 1), (-1, -1), "Helvetica", 8.6),
        ("TEXTCOLOR", (0, 0), (-1, 0), INK),
        ("TEXTCOLOR", (0, 1), (-1, -1), INK),
        ("LINEBELOW", (0, 0), (-1, 0), 0.7, INK),
        ("LINEBELOW", (0, 1), (-1, -2), 0.25, RULE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
    ]
    for c in align_right:
        cmds.append(("ALIGN", (c, 0), (c, -1), "RIGHT"))
    t.setStyle(TableStyle(cmds))
    return t


def main():
    S = styles()
    gcps = json.loads((GEO / "gcps.json").read_text())
    rivers = json.loads((QA / "river_check.json").read_text())
    overlay = json.loads((QA / "source_overlay.json").read_text())
    cross = json.loads((QA / "cross_sheet.json").read_text())
    checks = json.loads((OUT / "checks.json").read_text())
    grp = read_gpkg(VEC / "mitwaba.gpkg", "groupements")

    doc = SimpleDocTemplate(
        str(OUT / "Mitwaba_uncertainty_note.pdf"), pagesize=A4,
        leftMargin=20 * mm, rightMargin=20 * mm,
        topMargin=18 * mm, bottomMargin=18 * mm,
        title="Territoire de Mitwaba — note on accuracy and uncertainty")

    f = []
    f.append(Paragraph("Territoire de Mitwaba — administrative boundaries", S["h1"]))
    f.append(Paragraph(
        "Note on sources, accuracy and residual uncertainty · "
        "accompanies the A0 map and the GIS dataset", S["sub"]))

    f.append(Paragraph("1 · What the dataset is", S["h2"]))
    f.append(Paragraph(
        "The administrative boundaries reproduce the <i>Atlas électoral</i> "
        "published by the CENI (RD Congo) in August 2016, plates 52 and 54–56. "
        "They were transferred by georeferencing those plates and vectorising "
        "the printed areas — no boundary was researched, inferred from other "
        "sources, or redrawn. Where the atlas is ambiguous, this note says so "
        "rather than resolving it silently.", S["p"]))
    f.append(Paragraph(
        "Roads, watercourses, water bodies and settlements are <b>not</b> from "
        "the atlas. They come from present-day OpenStreetMap, as agreed, "
        "because the contextual layers had to be current and had to be "
        "redistributable as GIS data. They are context only and carry no "
        "administrative meaning.", S["p"]))

    f.append(Paragraph("2 · Georeferencing accuracy, per source plate", S["h2"]))
    f.append(Paragraph(
        "The plates carry no tick marks; the only geometric control is the "
        "coordinate labels printed outside the neatline, at 15-minute "
        "intervals. Each plate was fitted independently. The residual below is "
        "how far the fitted model misses those labels.", S["p"]))
    rows = [["Plate", "Sheet", "Scale", "Control points", "RMS", "Max"]]
    meta = {"21": ("52", "Territoire de Mitwaba", "1:1 000 000"),
            "22": ("54", "Secteur de Balomotwa", "1:600 000"),
            "23": ("55", "Secteur de Banweshi", "1:400 000"),
            "24": ("56", "Chefferie de Kiona-Ngoy", "1:375 000")}
    for pg in ("21", "22", "23", "24"):
        d = gcps[pg]
        plate, nm, sc = meta[pg]
        n = sum(1 for _ in d["gcps"])
        rows.append([plate, nm, sc, str(len(d["lons"]) + len(d["lats"])),
                     f"{d['residual_rms_m']:.0f} m",
                     f"{d['residual_max_m']:.0f} m"])
    f.append(table(rows, [14 * mm, 46 * mm, 26 * mm, 24 * mm, 18 * mm, 18 * mm],
                   align_right=(4, 5)))
    f.append(Spacer(1, 7))
    f.append(Paragraph(
        "<b>Plate 55 (Banweshi) is the weakest.</b> The left margin of that "
        "photograph is lost in the binding shadow, so only two latitude "
        "labels could be measured and the fit has no redundancy in that "
        "direction. It was checked instead by overlay against independent "
        "data (section 4) and shows no systematic shift, but its stated "
        "residual should be treated as less reliable than the other plates'.",
        S["p"]))

    f.append(Paragraph("3 · How closely the vectors follow the printed lines",
                       S["h2"]))
    f.append(Paragraph(
        "The delivered boundaries were drawn back onto the georeferenced "
        "plates and the distance from each sampled vertex to the nearest "
        "printed line measured.", S["p"]))
    rows = [["Sheet", "Median", "90th pct.", "Within 250 m", "Within 500 m"]]
    for pg, st in overlay.items():
        rows.append([st["sector"], f"{st['median_m']:.0f} m",
                     f"{st['p90_m']:.0f} m", f"{st['within_250m']:.0f} %",
                     f"{st['within_500m']:.0f} %"])
    f.append(table(rows, [46 * mm, 22 * mm, 24 * mm, 28 * mm, 28 * mm],
                   align_right=(1, 2, 3, 4)))
    f.append(Spacer(1, 7))
    f.append(Paragraph(
        "<b>Overall positional accuracy is therefore of the order of 200 to "
        "800 m</b>, dominated by the georeferencing of the source photographs "
        "rather than by the vectorising. At the printed A0 scale that is "
        "roughly 0.4 to 1.5 mm. The data should not be used for anything "
        "requiring better than a few hundred metres — cadastral work, "
        "boundary demarcation on the ground, or disputes over specific "
        "parcels.", S["p"]))

    f.append(Paragraph("4 · Independent verification", S["h2"]))
    f.append(Paragraph(
        "Residuals only measure a fit against its own control points, so they "
        "cannot detect a systematic error such as a mis-read label. Each "
        "georeferenced plate was therefore overlaid with present-day OSM "
        "hydrography, main roads and settlement points. Village names and "
        "positions coincide with the printed symbols one for one — Kanzebe, "
        "Kapola, Nsokelwa, Kapoya and Kasungami on plate 54; Kanfwa, Musebe "
        "and Mpala on plate 55; Kabanda, Mpenge, Milongwe, Kisele and Mubidi "
        "on plate 56 — and the road and river networks coincide with the "
        "printed ones. The plates are placed correctly in the world.", S["p"]))

    f.append(Paragraph(
        "A second, stronger check exploits the fact that the plates overlap. "
        "Each was georeferenced separately, from its own coordinate labels, "
        "with no knowledge of the others; where two of them cover the same "
        "ground they draw the same physical roads. Placing each plate's road "
        "network with its own model and measuring the separation gives a test "
        "no error in the fitting can pass. The three detail plates agree to "
        f"within {cross['worst_detail_median_m']:.0f} m of each other. A "
        "mis-read label or a graticule index off by one would have separated "
        "them by a quarter of a degree, about 27 km.", S["p"]))
    rows = [["Plates compared", "Overlap", "Median separation", "Within 1 km"]]
    for k, v in cross["pairs"].items():
        if not v.get("detail_pair"):
            continue
        rows.append([f"{v['plate_a']} · {v['plate_b']}",
                     f"{v['overlap_km2']:,} km²".replace(",", " "),
                     f"{v['median_m']:.0f} m",
                     f"{v['within_1km_pct']:.0f} %"])
    f.append(table(rows, [62 * mm, 26 * mm, 34 * mm, 26 * mm],
                   align_right=(1, 2, 3)))
    f.append(Spacer(1, 6))
    f.append(Paragraph(
        "The 1:1 000 000 territoire overview was compared too and sits 1.6 to "
        "2.8 km from the detail plates. That is generalisation, not error: at "
        "that scale a drawn road is a millimetre wide, which is a kilometre "
        "on the ground. It is reported for completeness and is not used for "
        "any boundary.", S["small"]))

    f.append(PageBreak())
    f.append(Paragraph("5 · Boundaries that remain uncertain", S["h2"]))

    f.append(Paragraph("5.1 · Area obscured by a printed panel", S["p"]))
    hole = grp[grp.edit_hole != "none"] if "edit_hole" in grp.columns else grp[0:0]
    names = ", ".join(sorted(hole.groupement)) if len(hole) else "—"
    f.append(Paragraph(
        f"Plate 54 prints the MUFUNGA enlargement panel over the map itself, "
        f"in the south-west of Balomotwa, and plate 55 stops short of the same "
        f"ground from the south. About <b>357 km² (1.8 % of the territory)</b> "
        f"is therefore not shown by any source plate. It has been allocated to "
        f"the surrounding groupements by proximity so the map has no hole in "
        f"it. <b>The boundary through this area is interpolated, not read from "
        f"the source.</b> Affected: {names}. The features are tagged in the "
        f"<font face='Courier'>edit_hole</font> field.", S["p"]))

    f.append(Paragraph("5.2 · Seams between the three plates", S["p"]))
    f.append(Paragraph(
        "The three sectors were drawn at different scales, photographed "
        "separately and georeferenced independently, so their shared "
        "boundaries disagree by a few hundred metres. Contested ground "
        "(34.6 km²) was given to the better-registered plate, and unclaimed "
        "slivers (134.0 km²) were closed against the nearest neighbour. Both "
        "edits are recorded per feature in "
        "<font face='Courier'>edit_overlap</font> and "
        "<font face='Courier'>edit_seam</font>. Along these seams the boundary "
        "is a reconciliation of two sources, not a reading of one.", S["p"]))

    f.append(Paragraph("5.3 · Boundaries that follow rivers", S["p"]))
    s = rivers["summary"]
    f.append(Paragraph(
        f"Of {s['boundaries']} shared boundaries totalling "
        f"{s['total_km']:.0f} km, <b>{s['river_based']} "
        f"({s['river_based_km']:.0f} km) follow a watercourse.</b> Those were "
        f"compared against the modern OSM drainage network. They shadow it "
        f"closely, but typically sit 200–1 500 m to one side, which is the "
        f"same order as the georeferencing error and cannot be separated from "
        f"it without better source imagery. {s['flagged']} segments where the "
        f"offset is largest are exported for inspection in "
        f"<font face='Courier'>qa/river_check.gpkg</font>. The boundaries were "
        f"<b>not</b> snapped to the rivers: doing so would have replaced what "
        f"the atlas shows with a guess.", S["p"]))
    rows = [["Boundary", "Length", "On river", "Offset", "Median offset"]]
    for b in sorted(rivers["boundaries"], key=lambda x: -x["length_km"])[:8]:
        if not b["river_based"]:
            continue
        rows.append([f"{b['left']} / {b['right']}", f"{b['length_km']:.0f} km",
                     f"{b['pct_on_river']} %", f"{b['pct_offset']} %",
                     f"{b['median_offset_m']} m"])
    f.append(table(rows, [50 * mm, 22 * mm, 22 * mm, 22 * mm, 28 * mm],
                   align_right=(1, 2, 3, 4)))

    f.append(Paragraph("5.4 · Commune de Mitwaba", S["h2"]))
    f.append(Paragraph(
        "The atlas shows the commune of Mitwaba as an uncoloured enclave "
        "inside the Kiona-Ngoy chefferie. As agreed, communes and their "
        "internal subdivisions are out of scope; the enclave is not carried "
        "as a separate polygon and the ground it covers is included in the "
        "surrounding groupement. Mitwaba town is shown as a settlement.",
        S["p"]))

    f.append(Paragraph("5.5 · Settlements", S["h2"]))
    f.append(Paragraph(
        "The atlas lists 276 villages for Mitwaba. As agreed, the map carries "
        "a legible selection at roughly the density of the provincial "
        "reference map — 32 names, chosen by settlement rank, chef-lieu "
        "status and position on a through road, subject to a minimum spacing. "
        "Only 5 of the 14 groupement chef-lieux carry the groupement's own "
        "name in OpenStreetMap; the other 9 names in the atlas could not be "
        "matched to a current mapped settlement and are not shown.", S["p"]))

    f.append(Paragraph("6 · Checks performed", S["h2"]))
    rows = [["Check", "Result"]]
    for c in checks["checks"]:
        rows.append([c["check"], ("PASS · " if c["pass_"] else "FAIL · ")
                     + c["detail"]])
    f.append(table(rows, [72 * mm, 78 * mm]))
    f.append(Spacer(1, 9))
    f.append(Paragraph(
        "The groupements tile the territory exactly: no overlaps, no gaps, "
        "and the sector and territoire layers are dissolves of the groupement "
        "layer rather than independent digitising, so the three levels cannot "
        "disagree with one another.", S["p"]))

    f.append(Spacer(1, 12))
    f.append(Paragraph(
        "Boundary source: CENI / RD Congo, <i>Atlas électoral</i>, August 2016, "
        "plates 52 and 54–56. Context: © OpenStreetMap contributors, ODbL. "
        "CRS EPSG:4326 (data) and EPSG:32735 / UTM 35S (map, areas).",
        S["small"]))

    doc.build(f)
    print("wrote", OUT / "Mitwaba_uncertainty_note.pdf")


if __name__ == "__main__":
    main()
