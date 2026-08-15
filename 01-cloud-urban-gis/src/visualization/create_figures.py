"""
Professional figure generation for Project 01, Amsterdam Cloud Urban GIS.
"""

from pathlib import Path

import contextily as cx
import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.patches import Patch

DATA_DIR = Path(__file__).parents[2] / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
OUTPUTS_DIR = Path(__file__).parents[2] / "outputs" / "figures"

TARGET_CRS = "EPSG:28992"
WEB_CRS = "EPSG:3857"

# Professional color scheme
COLORS = {
    "5min": "#2ecc71",
    "10min": "#f39c12",
    "15min": "#e74c3c",
    "buildings": "#95a5a6",
    "parks": "#27ae60",
    "water": "#3498db",
    "transit": "#9b59b6",
    "pois": "#e67e22",
}

plt.rcParams.update({
    "font.family": "sans-serif",
    "font.size": 10,
    "axes.titlesize": 14,
    "axes.titleweight": "bold",
    "figure.dpi": 150,
    "savefig.dpi": 300,
    "savefig.bbox": "tight",
    "savefig.pad_inches": 0.1,
})


def hero_figure():
    """Create hero figure showing the full urban GIS platform concept."""
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)

    fig, axes = plt.subplots(1, 3, figsize=(18, 7))

    # Panel 1: City context with buildings and parks
    boundary = gpd.read_file(RAW_DIR / "boundary.gpkg").to_crs(WEB_CRS)
    buildings = gpd.read_file(RAW_DIR / "buildings.gpkg").to_crs(WEB_CRS)
    parks = gpd.read_file(RAW_DIR / "parks.gpkg").to_crs(WEB_CRS)

    ax = axes[0]
    boundary.plot(ax=ax, facecolor="none", edgecolor="#2c3e50", linewidth=1.5)
    buildings.plot(ax=ax, color=COLORS["buildings"], alpha=0.3, linewidth=0)
    parks.plot(ax=ax, color=COLORS["parks"], alpha=0.5, linewidth=0)
    cx.add_basemap(ax, source=cx.providers.CartoDB.DarkMatterNoLabels, zoom=12)
    ax.set_title("Amsterdam Urban Fabric")
    ax.set_axis_off()

    # Panel 2: Accessibility isochrones
    ax = axes[1]
    if (PROCESSED_DIR / "isochrones_osmnx.gpkg").exists():
        isochrones = gpd.read_file(PROCESSED_DIR / "isochrones_osmnx.gpkg").to_crs(WEB_CRS)
        origins = gpd.read_file(PROCESSED_DIR / "origins.gpkg").to_crs(WEB_CRS)

        for time_min, color in [(15, COLORS["15min"]), (10, COLORS["10min"]), (5, COLORS["5min"])]:
            subset = isochrones[isochrones["time_minutes"] == time_min]
            subset.plot(ax=ax, color=color, alpha=0.4, edgecolor=color, linewidth=0.5)

        origins.plot(ax=ax, color="white", markersize=50, edgecolor="#2c3e50", linewidth=1.5, zorder=5)
        cx.add_basemap(ax, source=cx.providers.CartoDB.DarkMatterNoLabels, zoom=13)

        legend_elements = [
            Patch(facecolor=COLORS["5min"], alpha=0.6, label="5 min"),
            Patch(facecolor=COLORS["10min"], alpha=0.6, label="10 min"),
            Patch(facecolor=COLORS["15min"], alpha=0.6, label="15 min"),
        ]
        ax.legend(handles=legend_elements, loc="lower right", framealpha=0.9)
    ax.set_title("Walking Accessibility")
    ax.set_axis_off()

    # Panel 3: POI density
    ax = axes[2]
    if (RAW_DIR / "pois.gpkg").exists():
        pois = gpd.read_file(RAW_DIR / "pois.gpkg").to_crs(WEB_CRS)
        transit = gpd.read_file(RAW_DIR / "transit.gpkg").to_crs(WEB_CRS)
        boundary.plot(ax=ax, facecolor="none", edgecolor="#2c3e50", linewidth=1)
        transit.plot(ax=ax, color=COLORS["transit"], markersize=3, alpha=0.5)
        pois.plot(ax=ax, color=COLORS["pois"], markersize=2, alpha=0.4)
        cx.add_basemap(ax, source=cx.providers.CartoDB.DarkMatterNoLabels, zoom=12)
    ax.set_title("Amenities & Transit")
    ax.set_axis_off()

    fig.suptitle("Amsterdam Cloud Urban GIS", fontsize=18, fontweight="bold", y=0.98)
    plt.tight_layout()
    fig.savefig(OUTPUTS_DIR / "hero-cloud-urban-gis.png")
    plt.close()
    print(f"  Saved: hero-cloud-urban-gis.png")


def accessibility_figure():
    """Create detailed accessibility analysis figure."""
    if not (PROCESSED_DIR / "isochrones_osmnx.gpkg").exists():
        print("  Skipped: accessibility figure (data not ready)")
        return

    isochrones = gpd.read_file(PROCESSED_DIR / "isochrones_osmnx.gpkg")
    origins = gpd.read_file(PROCESSED_DIR / "origins.gpkg")

    n_origins = len(origins)
    fig, axes = plt.subplots(1, n_origins, figsize=(5 * n_origins, 6))
    if n_origins == 1:
        axes = [axes]

    for idx, (_, origin) in enumerate(origins.iterrows()):
        ax = axes[idx]
        name = origin["name"]
        origin_isos = isochrones[isochrones["origin_name"] == name].to_crs(WEB_CRS)

        for time_min, color in [(15, COLORS["15min"]), (10, COLORS["10min"]), (5, COLORS["5min"])]:
            subset = origin_isos[origin_isos["time_minutes"] == time_min]
            if not subset.empty:
                subset.plot(ax=ax, color=color, alpha=0.5, edgecolor=color, linewidth=1)

        # Plot origin point
        origin_pt = origins[origins["name"] == name].to_crs(WEB_CRS)
        origin_pt.plot(ax=ax, color="white", markersize=80, edgecolor="black", linewidth=2, zorder=5)

        cx.add_basemap(ax, source=cx.providers.CartoDB.Positron, zoom=14)
        ax.set_title(name, fontsize=11)
        ax.set_axis_off()

    fig.suptitle("Network-Based Walking Accessibility (OSMnx)", fontsize=14, fontweight="bold")
    plt.tight_layout()
    fig.savefig(OUTPUTS_DIR / "osmnx-accessibility.png")
    plt.close()
    print(f"  Saved: osmnx-accessibility.png")


def main():
    print("=" * 60)
    print("Generating Project 01 Figures")
    print("=" * 60)

    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)

    print("\n[1/2] Hero figure...")
    hero_figure()

    print("\n[2/2] Accessibility figure...")
    accessibility_figure()

    print("\nDone!")


if __name__ == "__main__":
    main()
