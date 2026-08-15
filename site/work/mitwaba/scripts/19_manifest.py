#!/usr/bin/env python3
"""
Step 19 - Check the delivery against the brief, item by item, and write the
README that ships with it.

Deliberately a checklist rather than a description: each line is one thing the
client asked for, tied to the file that satisfies it, and verified to exist on
disk before it is written down. If something is missing the script says so and
exits non-zero rather than producing a README that claims otherwise.

Output: DELIVERY.md, 06_output/manifest.json
"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from gpkg_io import read_gpkg

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "06_output"

# (requirement as stated by the client, file that satisfies it)
REQUIREMENTS = [
    ("Complete map, high-resolution PDF",
     "06_output/Mitwaba_A0.pdf"),
    ("High-resolution JPG or PNG version",
     "06_output/Mitwaba_A0.png"),
    ("High-resolution JPG version",
     "06_output/Mitwaba_A0.jpg"),
    ("QGIS project file",
     "05_qgis/Mitwaba.qgz"),
    ("GeoPackage of the administrative layers",
     "03_vector/mitwaba.gpkg"),
    ("Shapefile copies",
     "06_output/shapefiles/mitwaba_groupements.shp"),
    ("Separate vector layer - territoire",
     "06_output/shapefiles/mitwaba_territoire.shp"),
    ("Separate vector layer - secteurs / chefferie",
     "06_output/shapefiles/mitwaba_secteurs.shp"),
    ("Separate vector layer - groupements",
     "06_output/shapefiles/mitwaba_groupements.shp"),
    ("Note on uncertain / unverified boundaries",
     "06_output/Mitwaba_uncertainty_note.pdf"),
    ("Contextual layers - roads",
     "06_output/shapefiles/context_roads.shp"),
    ("Contextual layers - rivers and streams",
     "06_output/shapefiles/context_rivers.shp"),
    ("Contextual layers - water bodies",
     "06_output/shapefiles/context_water.shp"),
    ("Contextual layers - settlements with names",
     "06_output/shapefiles/context_places.shp"),
    ("Modern basemap (terrain)",
     "04_context/hillshade_utm35s.tif"),
    ("River-boundary review, flagged segments",
     "qa/river_check.gpkg"),
    ("Georeferenced source plates",
     "02_georef/page-22_4326.tif"),
    ("Acceptance checks, machine readable",
     "06_output/checks.json"),
]

MAP_ELEMENTS = ["Title", "Scale bar", "North arrow", "Legend by administrative "
                "level", "Source references", "Graticule with coordinates"]


def main():
    missing = []
    rows = []
    for req, rel in REQUIREMENTS:
        p = ROOT / rel
        ok = p.exists() and p.stat().st_size > 0
        size = f"{p.stat().st_size/1e6:.1f} MB" if ok else "MISSING"
        rows.append((req, rel, ok, size))
        if not ok:
            missing.append(rel)

    grp = read_gpkg(ROOT / "03_vector/mitwaba.gpkg", "groupements")
    sec = read_gpkg(ROOT / "03_vector/mitwaba.gpkg", "sectors")
    places = read_gpkg(ROOT / "04_context/context.gpkg", "places")
    checks = json.loads((OUT / "checks.json").read_text())
    rivers = json.loads((ROOT / "qa/river_check.json").read_text())
    overlay = json.loads((ROOT / "qa/source_overlay.json").read_text())
    gcps = json.loads((ROOT / "02_georef/gcps.json").read_text())

    print("delivery check")
    for req, rel, ok, size in rows:
        print(f"  {'OK  ' if ok else 'MISS'}  {req:<46} {rel}")

    area = grp.to_crs(32735).area.sum() / 1e6
    md = []
    md.append("# Territoire de Mitwaba — delivery\n")
    md.append("Administrative boundaries of Mitwaba Territory (Haut-Katanga, "
              "DR Congo), transferred from the CENI *Atlas électoral*, "
              "August 2016, onto a modern georeferenced base.\n")
    md.append(f"**{len(sec)} sectors / chefferie · {len(grp)} groupements · "
              f"{area:,.0f} km²**\n")

    md.append("## What to open first\n")
    md.append("| File | What it is |")
    md.append("|---|---|")
    md.append("| `06_output/Mitwaba_A0.pdf` | The map. A0 portrait, vector, "
              "print ready. |")
    md.append("| `06_output/Mitwaba_A0.png` / `.jpg` | Same map as an image, "
              "4966 × 7022 px. |")
    md.append("| `06_output/Mitwaba_uncertainty_note.pdf` | Accuracy and the "
              "boundaries that remain uncertain. Read this before using the "
              "data. |")
    md.append("| `05_qgis/Mitwaba.qgz` | QGIS project, styled, relative "
              "paths. |")
    md.append("| `03_vector/mitwaba.gpkg` | The dataset: `territoire`, "
              "`sectors`, `groupements`. |")
    md.append("| `06_output/shapefiles/` | The same layers as shapefiles. |\n")

    md.append("## Requirements checklist\n")
    md.append("| Requirement | Delivered as | |")
    md.append("|---|---|---|")
    for req, rel, ok, _ in rows:
        md.append(f"| {req} | `{rel}` | {'✅' if ok else '❌'} |")
    md.append("")
    md.append("Map sheet elements: " + ", ".join(MAP_ELEMENTS) + ".\n")

    md.append("## Accuracy in one paragraph\n")
    med = ", ".join(f"{v['sector']} {v['median_m']:.0f} m"
                    for v in overlay.values())
    rms = ", ".join(f"{gcps[p]['residual_rms_m']:.0f} m"
                    for p in ("22", "23", "24"))
    md.append(
        f"The source plates carry no tick marks, only coordinate labels "
        f"outside the neatline; each was fitted independently to those, with "
        f"residuals of {rms} RMS. The delivered boundaries sit a median of "
        f"{med} from the printed lines they reproduce. **Overall positional "
        f"accuracy is of the order of 200–800 m** — fine for a territory map "
        f"at A0, not suitable for demarcation on the ground.\n")

    md.append("## Checks\n")
    md.append("| Check | Result |")
    md.append("|---|---|")
    for c in checks["checks"]:
        md.append(f"| {c['check']} | {'PASS' if c['pass_'] else 'FAIL'} — "
                  f"{c['detail']} |")
    md.append("")
    s = rivers["summary"]
    md.append(f"{s['river_based']} of {s['boundaries']} shared boundaries "
              f"({s['river_based_km']:.0f} of {s['total_km']:.0f} km) follow a "
              f"watercourse; {s['flagged']} segments where the modern river "
              f"and the 2016 line diverge most are exported in "
              f"`qa/river_check.gpkg` for inspection. They were not snapped — "
              f"see the uncertainty note.\n")

    md.append("## Sources\n")
    md.append("- **Administrative boundaries** — CENI / RD Congo, *Atlas "
              "électoral*, August 2016, plates 52 and 54–56. Nothing was "
              "researched or inferred; every boundary is a transfer of a "
              "printed one.\n")
    md.append("- **Roads, hydrography, settlements** — © OpenStreetMap "
              "contributors, ODbL, extracted 2026. Current, and "
              "redistributable as GIS data.\n")
    md.append("- **Terrain** — AWS public terrain tiles (SRTM derived).\n")
    md.append("- CRS: EPSG:4326 for the data, EPSG:32735 (UTM 35S) for the "
              "map and all areas.\n")

    md.append("## Rebuilding\n")
    md.append("`scripts/` runs in numeric order, 01 to 19. Each step writes "
              "its own QA image into `qa/`, so any stage can be inspected "
              "without rerunning the rest.\n")

    (ROOT / "DELIVERY.md").write_text("\n".join(md), encoding="utf-8")
    (OUT / "manifest.json").write_text(json.dumps(
        dict(complete=not missing,
             files=[dict(requirement=r, path=p, present=o) for r, p, o, _ in rows]),
        indent=2))

    print(f"\nwrote {ROOT/'DELIVERY.md'}")
    if missing:
        print("MISSING:", *missing, sep="\n  ")
        return 1
    print("all required deliverables present")
    return 0


if __name__ == "__main__":
    sys.exit(main())
