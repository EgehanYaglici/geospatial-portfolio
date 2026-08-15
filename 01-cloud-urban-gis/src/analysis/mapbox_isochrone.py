"""
Mapbox Isochrone API comparison.
Fetches walking isochrones from Mapbox for the same origins
and compares with OSMnx-derived accessibility areas.
"""

import json
import os
import time
from pathlib import Path

import geopandas as gpd
import httpx
import pandas as pd
from dotenv import load_dotenv
from shapely.geometry import shape

DATA_DIR = Path(__file__).parents[2] / "data"
PROCESSED_DIR = DATA_DIR / "processed"
OUTPUTS_DIR = Path(__file__).parents[2] / "outputs" / "tables"

# Load .env from project root
load_dotenv(Path(__file__).parents[3] / ".env")

MAPBOX_TOKEN = os.getenv("MAPBOX_ACCESS_TOKEN", "")
MAPBOX_ISOCHRONE_URL = "https://api.mapbox.com/isochrone/v1/mapbox/walking"
TIME_LIMITS_MIN = [5, 10, 15]
TARGET_CRS = "EPSG:28992"


def fetch_mapbox_isochrone(lon: float, lat: float, minutes: list[int]) -> dict:
    """Fetch isochrone from Mapbox API."""
    params = {
        "contours_minutes": ",".join(str(m) for m in minutes),
        "polygons": "true",
        "access_token": MAPBOX_TOKEN,
    }
    url = f"{MAPBOX_ISOCHRONE_URL}/{lon},{lat}"
    response = httpx.get(url, params=params)
    response.raise_for_status()
    return response.json()


def main():
    print("=" * 60)
    print("Mapbox Isochrone API - Walking Accessibility")
    print("=" * 60)

    if not MAPBOX_TOKEN:
        print("\nWARNING: MAPBOX_ACCESS_TOKEN not set.")
        print("Mapbox comparison will be skipped.")
        print("Set token in .env and re-run to enable comparison.")
        return None

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)

    # Load origins (WGS84 for API calls)
    origins = gpd.read_file(PROCESSED_DIR / "origins.gpkg").to_crs("EPSG:4326")

    all_isochrones = []

    for _, origin in origins.iterrows():
        lon, lat = origin.geometry.x, origin.geometry.y
        name = origin["name"]
        print(f"\n  Fetching: {name} ({lat:.4f}, {lon:.4f})")

        try:
            result = fetch_mapbox_isochrone(lon, lat, TIME_LIMITS_MIN)
            features = result.get("features", [])

            for feature in features:
                props = feature.get("properties", {})
                contour_min = props.get("contour")
                geom = shape(feature["geometry"])

                all_isochrones.append({
                    "origin_name": name,
                    "time_minutes": contour_min,
                    "geometry": geom,
                })
                print(f"    {contour_min}min: fetched")

            time.sleep(0.5)  # Rate limiting courtesy
        except Exception as e:
            print(f"    ERROR: {e}")

    if not all_isochrones:
        print("\nNo Mapbox isochrones retrieved.")
        return None

    # Create GeoDataFrame
    mapbox_gdf = gpd.GeoDataFrame(all_isochrones, geometry="geometry", crs="EPSG:4326")
    mapbox_proj = mapbox_gdf.to_crs(TARGET_CRS)
    mapbox_proj["area_sqm"] = mapbox_proj.geometry.area
    mapbox_proj["area_hectares"] = mapbox_proj["area_sqm"] / 10000

    mapbox_proj.to_file(PROCESSED_DIR / "isochrones_mapbox.gpkg", driver="GPKG")
    mapbox_gdf.to_file(PROCESSED_DIR / "isochrones_mapbox_wgs84.geojson", driver="GeoJSON")

    print(f"\nMapbox isochrones saved: {len(mapbox_proj)} polygons")

    # Compare with OSMnx
    compare_isochrones(mapbox_proj)

    return mapbox_proj


def compare_isochrones(mapbox_gdf: gpd.GeoDataFrame):
    """Compare OSMnx and Mapbox isochrones."""
    osmnx_path = PROCESSED_DIR / "isochrones_osmnx.gpkg"
    if not osmnx_path.exists():
        print("\nOSMnx isochrones not found, comparison skipped.")
        return

    osmnx_gdf = gpd.read_file(osmnx_path)
    comparison = []

    for _, mapbox_row in mapbox_gdf.iterrows():
        origin = mapbox_row["origin_name"]
        time_min = mapbox_row["time_minutes"]

        osmnx_match = osmnx_gdf[
            (osmnx_gdf["origin_name"] == origin) &
            (osmnx_gdf["time_minutes"] == time_min)
        ]

        if len(osmnx_match) == 0:
            continue

        osmnx_geom = osmnx_match.iloc[0].geometry
        mapbox_geom = mapbox_row.geometry

        intersection = osmnx_geom.intersection(mapbox_geom)
        union = osmnx_geom.union(mapbox_geom)

        comparison.append({
            "origin": origin,
            "time_minutes": time_min,
            "osmnx_area_ha": osmnx_geom.area / 10000,
            "mapbox_area_ha": mapbox_geom.area / 10000,
            "intersection_ha": intersection.area / 10000,
            "union_ha": union.area / 10000,
            "overlap_ratio": intersection.area / union.area if union.area > 0 else 0,
            "osmnx_larger_pct": ((osmnx_geom.area - mapbox_geom.area) / mapbox_geom.area * 100)
            if mapbox_geom.area > 0 else 0,
        })

    if comparison:
        comp_df = pd.DataFrame(comparison)
        comp_df.to_csv(OUTPUTS_DIR / "osmnx_mapbox_comparison.csv", index=False)
        print("\nComparison saved to osmnx_mapbox_comparison.csv")
        print(comp_df.to_string(index=False))


if __name__ == "__main__":
    main()
