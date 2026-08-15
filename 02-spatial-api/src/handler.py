"""
AWS Lambda Spatial API Handler
Exposes PostGIS spatial queries as a REST API.
"""

import json
import os
from decimal import Decimal

import psycopg

DB_CONFIG = {
    "host": os.environ.get("DB_HOST", "localhost"),
    "port": int(os.environ.get("DB_PORT", 5432)),
    "dbname": os.environ.get("DB_NAME", "portfolio_gis"),
    "user": os.environ.get("DB_USER", "gis_user"),
    "password": os.environ.get("DB_PASSWORD", ""),
}

CORS_HEADERS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
}


def get_connection():
    return psycopg.connect(**DB_CONFIG)


def json_response(status_code: int, body: dict) -> dict:
    return {
        "statusCode": status_code,
        "headers": CORS_HEADERS,
        "body": json.dumps(body, default=str),
    }


def handle_health(event):
    """GET /health"""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT PostGIS_Version()")
                version = cur.fetchone()[0]
        return json_response(200, {
            "status": "healthy",
            "database": "connected",
            "postgis_version": version,
        })
    except Exception as e:
        return json_response(503, {"status": "unhealthy", "error": str(e)})


def handle_nearby(event):
    """
    GET /pois/nearby?lon=4.89&lat=52.37&radius=1000&category=supermarket
    Returns POIs within radius meters of the given point.
    """
    params = event.get("queryStringParameters") or {}

    try:
        lon = float(params["lon"])
        lat = float(params["lat"])
        radius = min(float(params.get("radius", 1000)), 5000)  # Cap at 5km
    except (KeyError, ValueError, TypeError) as e:
        return json_response(400, {"error": f"Invalid parameters: {e}"})

    if not (-180 <= lon <= 180 and -90 <= lat <= 90):
        return json_response(400, {"error": "Coordinates out of range"})

    category = params.get("category")

    query = """
        SELECT
            id, name, category,
            ST_Distance(
                geometry,
                ST_Transform(ST_SetSRID(ST_MakePoint(%s, %s), 4326), 28992)
            ) AS distance_m,
            ST_X(ST_Transform(geometry, 4326)) AS lon,
            ST_Y(ST_Transform(geometry, 4326)) AS lat
        FROM urban.pois
        WHERE ST_DWithin(
            geometry,
            ST_Transform(ST_SetSRID(ST_MakePoint(%s, %s), 4326), 28992),
            %s
        )
    """
    query_params = [lon, lat, lon, lat, radius]

    if category:
        query += " AND category = %s"
        query_params.append(category)

    query += " ORDER BY distance_m LIMIT 100"

    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, query_params)
                rows = cur.fetchall()
                columns = [desc[0] for desc in cur.description]

        features = []
        for row in rows:
            row_dict = dict(zip(columns, row))
            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [float(row_dict["lon"]), float(row_dict["lat"])],
                },
                "properties": {
                    "id": row_dict["id"],
                    "name": row_dict["name"],
                    "category": row_dict["category"],
                    "distance_m": round(float(row_dict["distance_m"]), 1),
                },
            })

        return json_response(200, {
            "type": "FeatureCollection",
            "features": features,
            "metadata": {
                "query_point": [lon, lat],
                "radius_m": radius,
                "category_filter": category,
                "total_results": len(features),
            },
        })
    except Exception as e:
        return json_response(500, {"error": str(e)})


def handle_nearest(event):
    """
    GET /facilities/nearest?lon=4.89&lat=52.37&category=hospital
    Returns the nearest facility of the given category.
    """
    params = event.get("queryStringParameters") or {}

    try:
        lon = float(params["lon"])
        lat = float(params["lat"])
        category = params["category"]
    except (KeyError, ValueError, TypeError) as e:
        return json_response(400, {"error": f"Missing parameters: {e}"})

    query = """
        SELECT
            id, name, category,
            ST_Distance(
                geometry,
                ST_Transform(ST_SetSRID(ST_MakePoint(%s, %s), 4326), 28992)
            ) AS distance_m,
            ST_X(ST_Transform(geometry, 4326)) AS lon,
            ST_Y(ST_Transform(geometry, 4326)) AS lat
        FROM urban.pois
        WHERE category = %s
        ORDER BY geometry <-> ST_Transform(ST_SetSRID(ST_MakePoint(%s, %s), 4326), 28992)
        LIMIT 1
    """

    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, [lon, lat, category, lon, lat])
                row = cur.fetchone()

        if not row:
            return json_response(404, {"error": f"No {category} found"})

        columns = ["id", "name", "category", "distance_m", "lon", "lat"]
        result = dict(zip(columns, row))

        return json_response(200, {
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [float(result["lon"]), float(result["lat"])],
            },
            "properties": {
                "id": result["id"],
                "name": result["name"],
                "category": result["category"],
                "distance_m": round(float(result["distance_m"]), 1),
            },
        })
    except Exception as e:
        return json_response(500, {"error": str(e)})


def handle_area_stats(event):
    """
    GET /stats/area?lon=4.89&lat=52.37&radius=1000
    Returns statistics for the area within radius of the point.
    """
    params = event.get("queryStringParameters") or {}

    try:
        lon = float(params["lon"])
        lat = float(params["lat"])
        radius = min(float(params.get("radius", 1000)), 5000)
    except (KeyError, ValueError, TypeError) as e:
        return json_response(400, {"error": f"Invalid parameters: {e}"})

    point_sql = "ST_Transform(ST_SetSRID(ST_MakePoint(%s, %s), 4326), 28992)"
    buffer_sql = f"ST_Buffer({point_sql}, %s)"

    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                # Building stats
                cur.execute(f"""
                    SELECT COUNT(*), COALESCE(SUM(ST_Area(geometry)), 0)
                    FROM urban.buildings
                    WHERE ST_DWithin(geometry, {point_sql}, %s)
                """, [lon, lat, radius])
                bld_count, bld_area = cur.fetchone()

                # POI counts by category
                cur.execute(f"""
                    SELECT category, COUNT(*)
                    FROM urban.pois
                    WHERE ST_DWithin(geometry, {point_sql}, %s)
                    GROUP BY category
                """, [lon, lat, radius])
                poi_counts = dict(cur.fetchall())

                # Park area
                cur.execute(f"""
                    SELECT COUNT(*), COALESCE(SUM(ST_Area(ST_Intersection(geometry, {buffer_sql}))), 0)
                    FROM urban.parks
                    WHERE ST_Intersects(geometry, {buffer_sql})
                """, [lon, lat, radius, lon, lat, radius])
                park_count, park_area = cur.fetchone()

                # Road length
                cur.execute(f"""
                    SELECT COALESCE(SUM(ST_Length(ST_Intersection(geometry, {buffer_sql}))), 0)
                    FROM urban.roads_walk
                    WHERE ST_Intersects(geometry, {buffer_sql})
                """, [lon, lat, radius, lon, lat, radius])
                road_length = cur.fetchone()[0]

        return json_response(200, {
            "query": {"center": [lon, lat], "radius_m": radius},
            "buildings": {"count": int(bld_count), "total_area_sqm": round(float(bld_area), 0)},
            "pois": poi_counts,
            "parks": {"count": int(park_count), "area_sqm": round(float(park_area), 0)},
            "roads": {"walkable_length_m": round(float(road_length), 0)},
        })
    except Exception as e:
        return json_response(500, {"error": str(e)})


def handle_intersects(event):
    """
    POST /analysis/intersects
    Body: {"geometry": <GeoJSON polygon>, "layers": ["buildings", "pois"]}
    Returns features intersecting the given polygon.
    """
    try:
        body = json.loads(event.get("body", "{}"))
    except json.JSONDecodeError:
        return json_response(400, {"error": "Invalid JSON body"})

    geometry = body.get("geometry")
    layers = body.get("layers", ["pois"])

    if not geometry or geometry.get("type") not in ("Polygon", "MultiPolygon"):
        return json_response(400, {"error": "Valid Polygon or MultiPolygon geometry required"})

    # Validate geometry size (prevent absurdly large requests)
    coords = geometry.get("coordinates", [[]])
    if geometry["type"] == "Polygon" and len(coords[0]) > 1000:
        return json_response(400, {"error": "Polygon too complex (>1000 vertices)"})

    geojson_str = json.dumps(geometry)
    results = {}

    layer_tables = {
        "buildings": "urban.buildings",
        "pois": "urban.pois",
        "transit": "urban.transit",
        "parks": "urban.parks",
    }

    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                for layer in layers:
                    table = layer_tables.get(layer)
                    if not table:
                        continue

                    cur.execute(f"""
                        SELECT COUNT(*)
                        FROM {table}
                        WHERE ST_Intersects(
                            geometry,
                            ST_Transform(ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326), 28992)
                        )
                    """, [geojson_str])
                    count = cur.fetchone()[0]
                    results[layer] = {"count": int(count)}

        return json_response(200, {"results": results})
    except Exception as e:
        return json_response(500, {"error": str(e)})


# Lambda entry point
def lambda_handler(event, context):
    """Route requests to appropriate handlers."""
    method = event.get("httpMethod", "GET")
    path = event.get("path", "/")

    # Handle CORS preflight
    if method == "OPTIONS":
        return json_response(200, {})

    routes = {
        ("GET", "/health"): handle_health,
        ("GET", "/pois/nearby"): handle_nearby,
        ("GET", "/facilities/nearest"): handle_nearest,
        ("GET", "/stats/area"): handle_area_stats,
        ("POST", "/analysis/intersects"): handle_intersects,
    }

    handler = routes.get((method, path))
    if handler:
        return handler(event)

    return json_response(404, {"error": f"Route not found: {method} {path}"})
