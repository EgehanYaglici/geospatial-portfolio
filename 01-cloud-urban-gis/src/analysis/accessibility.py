"""
Network-based Accessibility Analysis using OSMnx + NetworkX
Computes 5/10/15-minute walking isochrones from representative origins.
"""

import json
from pathlib import Path

import geopandas as gpd
import networkx as nx
import numpy as np
import osmnx as ox
from shapely.geometry import MultiPoint, Point
from shapely.ops import unary_union

DATA_DIR = Path(__file__).parents[2] / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
OUTPUTS_DIR = Path(__file__).parents[2] / "outputs"

PLACE = "Amsterdam, Netherlands"
TARGET_CRS = "EPSG:28992"
WALK_SPEED_KMH = 4.5  # Typical adult walking speed (km/h)
WALK_SPEED_MS = WALK_SPEED_KMH * 1000 / 3600  # ~1.25 m/s
TIME_LIMITS_MIN = [5, 10, 15]


def get_representative_origins() -> gpd.GeoDataFrame:
    """
    Select representative origin locations from OSM data.
    Uses actual POI/station locations rather than hardcoded coordinates.
    """
    origins = []

    # Amsterdam Centraal Station
    station = ox.features_from_place(
        PLACE, tags={"name": "Amsterdam Centraal", "railway": "station"}
    )
    if len(station) > 0:
        centroid = station.geometry.iloc[0].centroid
        origins.append({"name": "Amsterdam Centraal", "geometry": centroid})

    # Amsterdam Zuid Station
    zuid = ox.features_from_place(
        PLACE, tags={"name": "Amsterdam Zuid", "railway": "station"}
    )
    if len(zuid) > 0:
        centroid = zuid.geometry.iloc[0].centroid
        origins.append({"name": "Amsterdam Zuid", "geometry": centroid})

    # Sloterdijk Station
    sloterdijk = ox.features_from_place(
        PLACE, tags={"name": "Sloterdijk", "railway": "station"}
    )
    if len(sloterdijk) > 0:
        centroid = sloterdijk.geometry.iloc[0].centroid
        origins.append({"name": "Sloterdijk", "geometry": centroid})

    # Dam Square (central urban location)
    dam = ox.features_from_place(
        PLACE, tags={"name": "Dam", "place": "square"}
    )
    if len(dam) > 0:
        centroid = dam.geometry.iloc[0].centroid
        origins.append({"name": "Dam Square", "geometry": centroid})
    else:
        # Fallback: geocode Dam Square
        dam_point = ox.geocode("Dam Square, Amsterdam")
        origins.append({"name": "Dam Square", "geometry": Point(dam_point[1], dam_point[0])})

    # Oost - Muiderpoort station as outer neighbourhood representative
    muider = ox.features_from_place(
        PLACE, tags={"name": "Muiderpoort", "railway": "station"}
    )
    if len(muider) > 0:
        centroid = muider.geometry.iloc[0].centroid
        origins.append({"name": "Muiderpoort (Oost)", "geometry": centroid})

    gdf = gpd.GeoDataFrame(origins, geometry="geometry", crs="EPSG:4326")
    gdf = gdf.to_crs(TARGET_CRS)
    return gdf


def compute_isochrone(G, origin_node, time_limit_s) -> gpd.GeoDataFrame:
    """
    Compute network-based accessibility polygon for a given time limit.
    Returns a GeoDataFrame with the isochrone polygon.
    """
    subgraph = nx.ego_graph(G, origin_node, radius=time_limit_s, distance="travel_time")
    node_points = [Point(data["x"], data["y"]) for node, data in subgraph.nodes(data=True)]

    if len(node_points) < 3:
        return gpd.GeoDataFrame()

    # Create convex hull of reachable nodes as approximate accessibility area
    # For more accuracy, could use alpha shapes, but convex hull is defensible
    # for a portfolio demonstration of network accessibility
    multipoint = MultiPoint(node_points)
    # Use buffer + convex hull for smoother polygon
    buffered = multipoint.buffer(50)  # 50m buffer around reachable nodes
    polygon = unary_union(buffered)

    return polygon


def main():
    print("=" * 60)
    print("Accessibility Analysis - OSMnx/NetworkX")
    print(f"Walking speed: {WALK_SPEED_KMH} km/h ({WALK_SPEED_MS:.2f} m/s)")
    print("=" * 60)

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    # Load or create walk graph
    graph_path = RAW_DIR / "walk_graph.graphml"
    if graph_path.exists():
        print("\nLoading cached walk graph...")
        G = ox.load_graphml(graph_path)
    else:
        print("\nDownloading walk graph...")
        G = ox.graph_from_place(PLACE, network_type="walk")
        ox.save_graphml(G, graph_path)

    # Project graph for metric calculations
    G_proj = ox.project_graph(G, to_crs=TARGET_CRS)

    # Add travel time to edges
    for u, v, data in G_proj.edges(data=True):
        length_m = data.get("length", 0)
        data["travel_time"] = length_m / WALK_SPEED_MS

    # Get origins
    print("\nResolving representative origins...")
    origins = get_representative_origins()
    print(f"  Found {len(origins)} origins:")
    for _, row in origins.iterrows():
        print(f"    - {row['name']}")

    origins.to_file(PROCESSED_DIR / "origins.gpkg", driver="GPKG")

    # Compute isochrones
    print("\nComputing isochrones...")
    all_isochrones = []

    for idx, origin in origins.iterrows():
        origin_wgs84 = origins.to_crs("EPSG:4326").iloc[idx]
        nearest_node = ox.nearest_nodes(
            G_proj,
            origin.geometry.x,
            origin.geometry.y,
        )

        for time_min in TIME_LIMITS_MIN:
            time_s = time_min * 60
            polygon = compute_isochrone(G_proj, nearest_node, time_s)

            if polygon is not None and not polygon.is_empty:
                all_isochrones.append({
                    "origin_name": origin["name"],
                    "time_minutes": time_min,
                    "area_sqm": polygon.area,
                    "area_hectares": polygon.area / 10000,
                    "geometry": polygon,
                })
                print(f"  {origin['name']} - {time_min}min: {polygon.area/10000:.1f} ha")

    iso_gdf = gpd.GeoDataFrame(all_isochrones, geometry="geometry", crs=TARGET_CRS)
    iso_gdf.to_file(PROCESSED_DIR / "isochrones_osmnx.gpkg", driver="GPKG")

    # Save WGS84 version for web display
    iso_wgs84 = iso_gdf.to_crs("EPSG:4326")
    iso_wgs84.to_file(PROCESSED_DIR / "isochrones_osmnx_wgs84.geojson", driver="GeoJSON")

    print(f"\nIsochrones saved: {len(iso_gdf)} polygons")
    print(f"Output: {PROCESSED_DIR}")

    return iso_gdf


if __name__ == "__main__":
    main()
