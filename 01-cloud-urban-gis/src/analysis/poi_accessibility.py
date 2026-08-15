"""
POI Accessibility Statistics
Calculates what amenities are reachable within each isochrone.
"""

from pathlib import Path

import geopandas as gpd
import pandas as pd

DATA_DIR = Path(__file__).parents[2] / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
OUTPUTS_DIR = Path(__file__).parents[2] / "outputs" / "tables"

TARGET_CRS = "EPSG:28992"


def load_data():
    """Load isochrones and POIs."""
    isochrones = gpd.read_file(PROCESSED_DIR / "isochrones_osmnx.gpkg")
    pois = gpd.read_file(RAW_DIR / "pois.gpkg")
    transit = gpd.read_file(RAW_DIR / "transit.gpkg")
    parks = gpd.read_file(RAW_DIR / "parks.gpkg")
    return isochrones, pois, transit, parks


def compute_poi_stats(isochrones, pois, transit, parks) -> pd.DataFrame:
    """Count POIs within each isochrone polygon."""
    results = []

    for _, iso in isochrones.iterrows():
        iso_geom = iso.geometry
        origin = iso["origin_name"]
        time_min = iso["time_minutes"]

        # POI counts by category
        pois_within = pois[pois.geometry.within(iso_geom)]
        poi_counts = pois_within.groupby("category").size().to_dict()

        # Transit stops
        transit_within = transit[transit.geometry.within(iso_geom)]
        transit_count = len(transit_within)

        # Parks (intersecting, as parks may extend beyond isochrone)
        parks_intersecting = parks[parks.geometry.intersects(iso_geom)]
        park_count = len(parks_intersecting)
        park_area = parks_intersecting.geometry.intersection(iso_geom).area.sum()

        row = {
            "origin": origin,
            "time_minutes": time_min,
            "isochrone_area_ha": iso["area_hectares"],
            "supermarkets": poi_counts.get("supermarket", 0),
            "pharmacies": poi_counts.get("pharmacy", 0),
            "hospitals": poi_counts.get("hospital", 0),
            "clinics": poi_counts.get("clinic", 0),
            "schools": poi_counts.get("school", 0),
            "cafes": poi_counts.get("cafe", 0),
            "restaurants": poi_counts.get("restaurant", 0),
            "transit_stops": transit_count,
            "parks": park_count,
            "park_area_ha": park_area / 10000,
        }
        results.append(row)

    return pd.DataFrame(results)


def main():
    print("=" * 60)
    print("POI Accessibility Statistics")
    print("=" * 60)

    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)

    isochrones, pois, transit, parks = load_data()
    print(f"Loaded {len(isochrones)} isochrones, {len(pois)} POIs, {len(transit)} transit stops")

    stats = compute_poi_stats(isochrones, pois, transit, parks)
    stats.to_csv(OUTPUTS_DIR / "accessibility_stats.csv", index=False)

    print(f"\nResults saved to: {OUTPUTS_DIR / 'accessibility_stats.csv'}")
    print("\nSample (15-min walk):")
    print(stats[stats["time_minutes"] == 15].to_string(index=False))

    return stats


if __name__ == "__main__":
    main()
