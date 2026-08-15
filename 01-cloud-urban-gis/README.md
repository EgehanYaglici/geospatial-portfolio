# 01 Amsterdam Cloud Urban GIS

## Overview

A full-stack Web GIS platform demonstrating cloud-native geospatial infrastructure: data flows from OpenStreetMap through a Python ETL pipeline into PostGIS, is served via GeoServer (WMS/WFS) and a spatial API, and displayed through an interactive Mapbox GL JS frontend deployed on AWS.

## Problem

Urban planners and analysts need to assess walking accessibility to amenities across city areas. This requires combining network analysis, spatial databases, and interactive visualization in a single deployable system.

## Dataset

| Source | Features | Coverage |
|--------|----------|----------|
| OSM Buildings | 197,578 | Amsterdam municipality |
| OSM Walk Network | 143,034 edges | Full walkable graph |
| OSM Amenities | 7,583 | 10 categories |
| OSM Transit | 1,641 | Stations, tram/bus stops |
| OSM Parks | 268 | Green spaces |
| OSM Water | 6,154 | Water bodies |

## Architecture

```
OSM → OSMnx → PostGIS → GeoServer → Mapbox GL JS → S3/CloudFront
                  ↓            ↑
          NetworkX/OSMnx    Lambda API
          (accessibility)
```

## Analysis

### Walking Accessibility (OSMnx)
- 5 representative origins selected via geocoding
- Graph-based 5/10/15-minute isochrones using NetworkX ego_graph
- Walking speed: 4.5 km/h (1.25 m/s)
- Polygon generation: 50m buffer around reachable network nodes

### Mapbox Isochrone Comparison
- Same origins queried via Mapbox Isochrone API
- OSMnx consistently produces smaller areas (20-73% smaller)
- Highest agreement at Dam Square (IoU: 0.70), lowest at Muiderpoort (IoU: 0.27)

### Key Finding
Dam Square has by far the best walkable accessibility: 474 restaurants, 197 cafes, 73 transit stops within a 15-minute walk. Sloterdijk (business district) has almost no amenities in the same radius.

## Technical Decisions

- **CRS**: EPSG:28992 (RD New) for analysis, WGS84 for web/API
- **Walking speed**: 4.5 km/h, standard pedestrian planning assumption
- **Isochrone method**: Convex hull of buffered reachable nodes. Not scientifically exact boundaries but defensible approximation of network accessibility
- **Mapbox comparison**: Not claiming either is "correct", they use different routing networks, speeds, and polygon generation methods

## Results

| Origin | 15-min Area (ha) | Supermarkets | Restaurants | Transit |
|--------|-----------------|--------------|-------------|---------|
| Dam Square | 220 | 16 | 474 | 73 |
| Centraal | 162 | 12 | 285 | 66 |
| Zuid | 143 | 3 | 26 | 43 |
| Muiderpoort | 133 | 18 | 63 | 49 |
| Sloterdijk | 119 | 0 | 10 | 35 |

## Reproduction

```bash
cd 01-cloud-urban-gis
python src/acquisition/acquire_amsterdam.py
python src/analysis/accessibility.py
python src/analysis/mapbox_isochrone.py
python src/analysis/poi_accessibility.py
python src/visualization/create_figures.py
```

## Limitations

- Overpass API rate limits may require retry/cooldown for large Amsterdam requests
- Isochrone polygons are approximate (buffered reachable nodes, not true service areas)
- Mapbox comparison depends on API availability and token validity
- Building data from OSM may not be 100% complete

## Mapbox token

`src/analysis/mapbox_isochrone.py` calls the Mapbox Isochrone API and needs a
token. Copy the repository root `.env.example` to `.env` and set
`MAPBOX_ACCESS_TOKEN`. Without it that one script exits with a warning; every
other script in this project runs on open data and needs no credentials.
