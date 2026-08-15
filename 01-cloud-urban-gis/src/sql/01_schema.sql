-- Amsterdam Urban GIS Database Schema
-- Database: portfolio_gis
-- Schema: urban

CREATE EXTENSION IF NOT EXISTS postgis;

CREATE SCHEMA IF NOT EXISTS urban;

-- City boundary
CREATE TABLE IF NOT EXISTS urban.boundary (
    id SERIAL PRIMARY KEY,
    name TEXT,
    geometry GEOMETRY(MultiPolygon, 28992) NOT NULL
);

-- Walkable road network
CREATE TABLE IF NOT EXISTS urban.roads_walk (
    id SERIAL PRIMARY KEY,
    osmid BIGINT,
    name TEXT,
    highway TEXT,
    length_m DOUBLE PRECISION,
    geometry GEOMETRY(LineString, 28992) NOT NULL
);

-- Drivable road network
CREATE TABLE IF NOT EXISTS urban.roads_drive (
    id SERIAL PRIMARY KEY,
    osmid BIGINT,
    name TEXT,
    highway TEXT,
    lanes TEXT,
    maxspeed TEXT,
    length_m DOUBLE PRECISION,
    geometry GEOMETRY(LineString, 28992) NOT NULL
);

-- Building footprints
CREATE TABLE IF NOT EXISTS urban.buildings (
    id SERIAL PRIMARY KEY,
    osmid BIGINT,
    name TEXT,
    building_type TEXT,
    height TEXT,
    levels TEXT,
    area_sqm DOUBLE PRECISION,
    geometry GEOMETRY(Polygon, 28992) NOT NULL
);

-- Points of interest
CREATE TABLE IF NOT EXISTS urban.pois (
    id SERIAL PRIMARY KEY,
    osmid BIGINT,
    name TEXT,
    category TEXT NOT NULL,
    geometry GEOMETRY(Point, 28992) NOT NULL
);

-- Public transit stops
CREATE TABLE IF NOT EXISTS urban.transit (
    id SERIAL PRIMARY KEY,
    osmid BIGINT,
    name TEXT,
    transit_type TEXT,
    geometry GEOMETRY(Point, 28992) NOT NULL
);

-- Parks and green spaces
CREATE TABLE IF NOT EXISTS urban.parks (
    id SERIAL PRIMARY KEY,
    osmid BIGINT,
    name TEXT,
    area_sqm DOUBLE PRECISION,
    geometry GEOMETRY(Polygon, 28992) NOT NULL
);

-- Water bodies
CREATE TABLE IF NOT EXISTS urban.water (
    id SERIAL PRIMARY KEY,
    osmid BIGINT,
    name TEXT,
    area_sqm DOUBLE PRECISION,
    geometry GEOMETRY(Polygon, 28992) NOT NULL
);

-- Analysis origins
CREATE TABLE IF NOT EXISTS urban.origins (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    geometry GEOMETRY(Point, 28992) NOT NULL
);

-- OSMnx-derived isochrones
CREATE TABLE IF NOT EXISTS urban.isochrones_osmnx (
    id SERIAL PRIMARY KEY,
    origin_name TEXT NOT NULL,
    time_minutes INTEGER NOT NULL,
    area_sqm DOUBLE PRECISION,
    area_hectares DOUBLE PRECISION,
    geometry GEOMETRY(Polygon, 28992) NOT NULL
);

-- Mapbox-derived isochrones
CREATE TABLE IF NOT EXISTS urban.isochrones_mapbox (
    id SERIAL PRIMARY KEY,
    origin_name TEXT NOT NULL,
    time_minutes INTEGER NOT NULL,
    area_sqm DOUBLE PRECISION,
    area_hectares DOUBLE PRECISION,
    geometry GEOMETRY(Polygon, 28992) NOT NULL
);

-- Accessibility statistics
CREATE TABLE IF NOT EXISTS urban.accessibility_stats (
    id SERIAL PRIMARY KEY,
    origin_name TEXT NOT NULL,
    time_minutes INTEGER NOT NULL,
    source TEXT NOT NULL, -- 'osmnx' or 'mapbox'
    supermarkets INTEGER DEFAULT 0,
    pharmacies INTEGER DEFAULT 0,
    hospitals INTEGER DEFAULT 0,
    schools INTEGER DEFAULT 0,
    transit_stops INTEGER DEFAULT 0,
    parks INTEGER DEFAULT 0,
    park_area_ha DOUBLE PRECISION DEFAULT 0
);
