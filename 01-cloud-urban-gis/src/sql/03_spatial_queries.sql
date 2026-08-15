-- =============================================================
-- Spatial SQL Demonstrations, Amsterdam Urban GIS
-- =============================================================

-- ---------------------------------------------------------
-- 1. POI count within 15-min walking isochrone per origin
--    Uses: ST_Within
-- ---------------------------------------------------------
SELECT
    i.origin_name,
    p.category,
    COUNT(*) AS poi_count
FROM urban.isochrones_osmnx i
JOIN urban.pois p ON ST_Within(p.geometry, i.geometry)
WHERE i.time_minutes = 15
GROUP BY i.origin_name, p.category
ORDER BY i.origin_name, poi_count DESC;


-- ---------------------------------------------------------
-- 2. Building density within selected area
--    Uses: ST_Intersects, ST_Area
-- ---------------------------------------------------------
SELECT
    i.origin_name,
    i.time_minutes,
    COUNT(b.id) AS building_count,
    SUM(ST_Area(b.geometry)) AS total_footprint_sqm,
    SUM(ST_Area(b.geometry)) / ST_Area(i.geometry) * 100 AS footprint_coverage_pct
FROM urban.isochrones_osmnx i
JOIN urban.buildings b ON ST_Intersects(b.geometry, i.geometry)
WHERE i.time_minutes = 15
GROUP BY i.origin_name, i.time_minutes, ST_Area(i.geometry)
ORDER BY footprint_coverage_pct DESC;


-- ---------------------------------------------------------
-- 3. Nearest hospital from each origin
--    Uses: ST_Distance, ST_Transform
-- ---------------------------------------------------------
SELECT DISTINCT ON (o.name)
    o.name AS origin,
    p.name AS hospital_name,
    ST_Distance(o.geometry, p.geometry) AS distance_m
FROM urban.origins o
CROSS JOIN LATERAL (
    SELECT name, geometry
    FROM urban.pois
    WHERE category = 'hospital'
    ORDER BY o.geometry <-> geometry
    LIMIT 1
) p
ORDER BY o.name, distance_m;


-- ---------------------------------------------------------
-- 4. Nearest pharmacy from each origin
--    Uses: <-> distance operator, ST_Distance
-- ---------------------------------------------------------
SELECT DISTINCT ON (o.name)
    o.name AS origin,
    p.name AS pharmacy_name,
    ST_Distance(o.geometry, p.geometry) AS distance_m
FROM urban.origins o
CROSS JOIN LATERAL (
    SELECT name, geometry
    FROM urban.pois
    WHERE category = 'pharmacy'
    ORDER BY o.geometry <-> geometry
    LIMIT 1
) p
ORDER BY o.name, distance_m;


-- ---------------------------------------------------------
-- 5. Transit stops within 500m buffer of each origin
--    Uses: ST_DWithin
-- ---------------------------------------------------------
SELECT
    o.name AS origin,
    t.transit_type,
    COUNT(*) AS stop_count
FROM urban.origins o
JOIN urban.transit t ON ST_DWithin(o.geometry, t.geometry, 500)
GROUP BY o.name, t.transit_type
ORDER BY o.name, stop_count DESC;


-- ---------------------------------------------------------
-- 6. Park area intersecting accessibility zones
--    Uses: ST_Intersection, ST_Area, ST_Contains
-- ---------------------------------------------------------
SELECT
    i.origin_name,
    i.time_minutes,
    COUNT(pk.id) AS park_count,
    SUM(ST_Area(ST_Intersection(pk.geometry, i.geometry))) / 10000 AS park_area_ha,
    SUM(ST_Area(ST_Intersection(pk.geometry, i.geometry))) / ST_Area(i.geometry) * 100 AS park_coverage_pct
FROM urban.isochrones_osmnx i
JOIN urban.parks pk ON ST_Intersects(pk.geometry, i.geometry)
GROUP BY i.origin_name, i.time_minutes, ST_Area(i.geometry)
ORDER BY i.origin_name, i.time_minutes;


-- ---------------------------------------------------------
-- 7. Total road length within each isochrone
--    Uses: ST_Intersection, ST_Length
-- ---------------------------------------------------------
SELECT
    i.origin_name,
    i.time_minutes,
    SUM(ST_Length(ST_Intersection(r.geometry, i.geometry))) / 1000 AS road_km
FROM urban.isochrones_osmnx i
JOIN urban.roads_walk r ON ST_Intersects(r.geometry, i.geometry)
GROUP BY i.origin_name, i.time_minutes
ORDER BY i.origin_name, i.time_minutes;


-- ---------------------------------------------------------
-- 8. Centroid-based cluster analysis
--    Uses: ST_Centroid, ST_Union
-- ---------------------------------------------------------
SELECT
    category,
    ST_X(ST_Centroid(ST_Union(geometry))) AS cluster_x,
    ST_Y(ST_Centroid(ST_Union(geometry))) AS cluster_y,
    COUNT(*) AS count
FROM urban.pois
GROUP BY category
ORDER BY count DESC;


-- ---------------------------------------------------------
-- 9. Buildings entirely within parks
--    Uses: ST_Contains
-- ---------------------------------------------------------
SELECT
    pk.name AS park_name,
    COUNT(b.id) AS buildings_in_park,
    SUM(ST_Area(b.geometry)) AS total_building_area_sqm
FROM urban.parks pk
JOIN urban.buildings b ON ST_Contains(pk.geometry, b.geometry)
GROUP BY pk.name
HAVING COUNT(b.id) > 0
ORDER BY buildings_in_park DESC
LIMIT 20;


-- ---------------------------------------------------------
-- 10. Water proximity, buildings within 100m of water
--     Uses: ST_DWithin
-- ---------------------------------------------------------
SELECT
    COUNT(*) AS buildings_near_water,
    AVG(ST_Area(b.geometry)) AS avg_footprint_sqm
FROM urban.buildings b
WHERE EXISTS (
    SELECT 1 FROM urban.water w
    WHERE ST_DWithin(b.geometry, w.geometry, 100)
);


-- ---------------------------------------------------------
-- 11. Transform and display origins in WGS84
--     Uses: ST_Transform, ST_X, ST_Y
-- ---------------------------------------------------------
SELECT
    name,
    ST_X(ST_Transform(geometry, 4326)) AS longitude,
    ST_Y(ST_Transform(geometry, 4326)) AS latitude
FROM urban.origins;
