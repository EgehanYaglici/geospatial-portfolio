-- Spatial indexes for urban schema

CREATE INDEX IF NOT EXISTS idx_boundary_geom ON urban.boundary USING GIST (geometry);
CREATE INDEX IF NOT EXISTS idx_roads_walk_geom ON urban.roads_walk USING GIST (geometry);
CREATE INDEX IF NOT EXISTS idx_roads_drive_geom ON urban.roads_drive USING GIST (geometry);
CREATE INDEX IF NOT EXISTS idx_buildings_geom ON urban.buildings USING GIST (geometry);
CREATE INDEX IF NOT EXISTS idx_pois_geom ON urban.pois USING GIST (geometry);
CREATE INDEX IF NOT EXISTS idx_pois_category ON urban.pois (category);
CREATE INDEX IF NOT EXISTS idx_transit_geom ON urban.transit USING GIST (geometry);
CREATE INDEX IF NOT EXISTS idx_parks_geom ON urban.parks USING GIST (geometry);
CREATE INDEX IF NOT EXISTS idx_water_geom ON urban.water USING GIST (geometry);
CREATE INDEX IF NOT EXISTS idx_origins_geom ON urban.origins USING GIST (geometry);
CREATE INDEX IF NOT EXISTS idx_isochrones_osmnx_geom ON urban.isochrones_osmnx USING GIST (geometry);
CREATE INDEX IF NOT EXISTS idx_isochrones_mapbox_geom ON urban.isochrones_mapbox USING GIST (geometry);
CREATE INDEX IF NOT EXISTS idx_isochrones_osmnx_origin ON urban.isochrones_osmnx (origin_name, time_minutes);
CREATE INDEX IF NOT EXISTS idx_isochrones_mapbox_origin ON urban.isochrones_mapbox (origin_name, time_minutes);

ANALYZE urban.boundary;
ANALYZE urban.roads_walk;
ANALYZE urban.roads_drive;
ANALYZE urban.buildings;
ANALYZE urban.pois;
ANALYZE urban.transit;
ANALYZE urban.parks;
ANALYZE urban.water;
ANALYZE urban.origins;
ANALYZE urban.isochrones_osmnx;
ANALYZE urban.isochrones_mapbox;
