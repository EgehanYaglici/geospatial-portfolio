"""
Amsterdam OpenStreetMap Data Acquisition
Acquires transport, buildings, amenities, transit, and urban features
using OSMnx for the Amsterdam study area.
"""

import json
import time
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import osmnx as ox
import pandas as pd

DATA_DIR = Path(__file__).parents[2] / "data"
RAW_DIR = DATA_DIR / "raw"
METADATA_DIR = Path(__file__).parents[2] / "metadata"

PLACE = "Amsterdam, Netherlands"
TARGET_CRS = "EPSG:28992"  # Amersfoort / RD New, Dutch national grid


def ensure_dirs():
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    METADATA_DIR.mkdir(parents=True, exist_ok=True)


def acquire_boundary() -> gpd.GeoDataFrame:
    """Get Amsterdam administrative boundary."""
    gdf = ox.geocode_to_gdf(PLACE)
    gdf = gdf.to_crs(TARGET_CRS)
    gdf.to_file(RAW_DIR / "boundary.gpkg", driver="GPKG")
    return gdf


def acquire_road_networks() -> dict:
    """Acquire walkable and drivable road networks."""
    results = {}

    walk_graph = ox.graph_from_place(PLACE, network_type="walk")
    walk_nodes, walk_edges = ox.graph_to_gdfs(walk_graph)
    walk_edges_proj = walk_edges.to_crs(TARGET_CRS)
    walk_edges_proj.to_file(RAW_DIR / "roads_walk.gpkg", driver="GPKG")
    results["roads_walk"] = len(walk_edges_proj)

    drive_graph = ox.graph_from_place(PLACE, network_type="drive")
    drive_nodes, drive_edges = ox.graph_to_gdfs(drive_graph)
    drive_edges_proj = drive_edges.to_crs(TARGET_CRS)
    drive_edges_proj.to_file(RAW_DIR / "roads_drive.gpkg", driver="GPKG")
    results["roads_drive"] = len(drive_edges_proj)

    # Save walk graph for accessibility analysis
    ox.save_graphml(walk_graph, RAW_DIR / "walk_graph.graphml")
    results["walk_graph_nodes"] = len(walk_nodes)

    return results


def acquire_buildings() -> int:
    """Acquire building footprints."""
    tags = {"building": True}
    gdf = ox.features_from_place(PLACE, tags=tags)
    gdf = gdf[gdf.geometry.type.isin(["Polygon", "MultiPolygon"])].copy()
    gdf = gdf.to_crs(TARGET_CRS)
    gdf.to_file(RAW_DIR / "buildings.gpkg", driver="GPKG")
    return len(gdf)


def acquire_amenities() -> dict:
    """Acquire various amenity categories."""
    categories = {
        "supermarket": {"shop": "supermarket"},
        "pharmacy": {"amenity": "pharmacy"},
        "hospital": {"amenity": "hospital"},
        "clinic": {"amenity": "clinic"},
        "school": {"amenity": "school"},
        "university": {"amenity": "university"},
        "cafe": {"amenity": "cafe"},
        "restaurant": {"amenity": "restaurant"},
        "fuel": {"amenity": "fuel"},
        "parking": {"amenity": "parking"},
    }

    all_pois = []
    counts = {}

    for cat_name, tags in categories.items():
        try:
            gdf = ox.features_from_place(PLACE, tags=tags)
            gdf = gdf.copy()
            gdf["category"] = cat_name
            gdf = gdf.to_crs(TARGET_CRS)
            gdf["geometry"] = gdf.geometry.centroid
            all_pois.append(gdf[["geometry", "category", "name"]].copy())
            counts[cat_name] = len(gdf)
        except Exception as e:
            print(f"  Warning: {cat_name} acquisition failed: {e}")
            counts[cat_name] = 0

    if all_pois:
        pois = pd.concat(all_pois, ignore_index=True)
        pois = gpd.GeoDataFrame(pois, geometry="geometry", crs=TARGET_CRS)
        pois.to_file(RAW_DIR / "pois.gpkg", driver="GPKG")

    return counts


def acquire_transit() -> int:
    """Acquire public transit stops."""
    transit_tags = {
        "railway": ["station", "halt", "tram_stop"],
        "highway": "bus_stop",
        "station": "subway",
    }

    all_transit = []
    for tag_key, tag_val in transit_tags.items():
        try:
            gdf = ox.features_from_place(PLACE, tags={tag_key: tag_val})
            gdf = gdf.copy()
            gdf["transit_type"] = tag_key
            gdf = gdf.to_crs(TARGET_CRS)
            gdf["geometry"] = gdf.geometry.centroid
            all_transit.append(gdf[["geometry", "transit_type", "name"]].copy())
        except Exception:
            pass

    if all_transit:
        transit = pd.concat(all_transit, ignore_index=True)
        transit = gpd.GeoDataFrame(transit, geometry="geometry", crs=TARGET_CRS)
        transit.to_file(RAW_DIR / "transit.gpkg", driver="GPKG")
        return len(transit)
    return 0


def acquire_parks() -> int:
    """Acquire parks and green spaces."""
    tags = {"leisure": "park"}
    gdf = ox.features_from_place(PLACE, tags=tags)
    gdf = gdf[gdf.geometry.type.isin(["Polygon", "MultiPolygon"])].copy()
    gdf = gdf.to_crs(TARGET_CRS)
    gdf.to_file(RAW_DIR / "parks.gpkg", driver="GPKG")
    return len(gdf)


def acquire_water() -> int:
    """Acquire water bodies."""
    tags = {"natural": "water"}
    gdf = ox.features_from_place(PLACE, tags=tags)
    gdf = gdf[gdf.geometry.type.isin(["Polygon", "MultiPolygon"])].copy()
    gdf = gdf.to_crs(TARGET_CRS)
    gdf.to_file(RAW_DIR / "water.gpkg", driver="GPKG")
    return len(gdf)


def save_metadata(results: dict):
    """Save acquisition metadata."""
    metadata = {
        "acquisition_timestamp": datetime.now(timezone.utc).isoformat(),
        "source": "OpenStreetMap via OSMnx",
        "place_query": PLACE,
        "target_crs": TARGET_CRS,
        "feature_counts": results,
    }
    with open(METADATA_DIR / "acquisition_metadata.json", "w") as f:
        json.dump(metadata, f, indent=2)


def main():
    print("=" * 60)
    print("Amsterdam OpenStreetMap Data Acquisition")
    print("=" * 60)

    ensure_dirs()
    results = {}

    print("\n[1/7] Acquiring boundary...")
    t0 = time.time()
    boundary = acquire_boundary()
    print(f"  Done ({time.time()-t0:.1f}s)")
    results["boundary"] = 1

    print("\n[2/7] Acquiring road networks...")
    t0 = time.time()
    road_counts = acquire_road_networks()
    results.update(road_counts)
    print(f"  Walk edges: {road_counts['roads_walk']:,}")
    print(f"  Drive edges: {road_counts['roads_drive']:,}")
    print(f"  Done ({time.time()-t0:.1f}s)")

    print("\n[3/7] Acquiring buildings...")
    t0 = time.time()
    results["buildings"] = acquire_buildings()
    print(f"  Buildings: {results['buildings']:,}")
    print(f"  Done ({time.time()-t0:.1f}s)")

    print("\n[4/7] Acquiring amenities/POIs...")
    t0 = time.time()
    poi_counts = acquire_amenities()
    results["pois"] = poi_counts
    for cat, count in poi_counts.items():
        print(f"  {cat}: {count:,}")
    print(f"  Done ({time.time()-t0:.1f}s)")

    print("\n[5/7] Acquiring transit stops...")
    t0 = time.time()
    results["transit"] = acquire_transit()
    print(f"  Transit stops: {results['transit']:,}")
    print(f"  Done ({time.time()-t0:.1f}s)")

    print("\n[6/7] Acquiring parks...")
    t0 = time.time()
    results["parks"] = acquire_parks()
    print(f"  Parks: {results['parks']:,}")
    print(f"  Done ({time.time()-t0:.1f}s)")

    print("\n[7/7] Acquiring water bodies...")
    t0 = time.time()
    results["water"] = acquire_water()
    print(f"  Water: {results['water']:,}")
    print(f"  Done ({time.time()-t0:.1f}s)")

    save_metadata(results)

    print("\n" + "=" * 60)
    print("Acquisition complete!")
    print(f"Data saved to: {RAW_DIR}")
    print(f"Metadata saved to: {METADATA_DIR}")
    print("=" * 60)


if __name__ == "__main__":
    main()
