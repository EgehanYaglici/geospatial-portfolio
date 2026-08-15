# Architecture

## System Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                         DATA SOURCES                                  │
├──────────────┬──────────────┬──────────────┬────────────────────────┤
│ OpenStreetMap│  PDOK AHN    │ Copernicus   │  Mapbox Services       │
│ (OSMnx)     │  (WCS/Atom)  │ (STAC/S1)    │  (Isochrone API)       │
└──────┬───────┴──────┬───────┴──────┬───────┴──────────┬─────────────┘
       │              │              │                   │
       v              v              v                   │
┌─────────────────────────────────────────┐             │
│         Python ETL Pipeline             │             │
│  acquire → inspect → normalize →        │             │
│  validate → repair → transform →        │             │
│  export → load                          │             │
└──────────────┬──────────────────────────┘             │
               │                                         │
    ┌──────────┼──────────────┐                         │
    │          │              │                          │
    v          v              v                          │
┌────────┐ ┌──────────┐ ┌─────────┐                    │
│ AWS S3 │ │ PostGIS  │ │ Raster  │                    │
│raw/    │ │ (RDS)    │ │ outputs │                    │
│proc/   │ │ spatial  │ │ GeoTIFF │                    │
│reports │ │ indexes  │ │ PNG     │                    │
└────────┘ └────┬─────┘ └─────────┘                    │
                │                                       │
        ┌───────┼──────────────┐                       │
        │       │              │                        │
        v       v              v                        │
   ┌────────┐ ┌──────────┐ ┌──────────┐              │
   │GeoSrvr │ │ Lambda   │ │ Static   │              │
   │WMS/WFS │ │ Spatial  │ │ Frontend │              │
   │Docker  │ │ API      │ │ S3+CF    │              │
   └───┬────┘ └────┬─────┘ └────┬─────┘              │
       │            │            │                     │
       └────────────┼────────────┘                     │
                    │                                   │
                    v                                   v
            ┌───────────────────────────────────────────────┐
            │            Mapbox GL JS Frontend               │
            │  • Interactive map with analysis layers        │
            │  • Layer toggles, accessibility stats          │
            │  • 3D building extrusion (Rotterdam)           │
            │  • Nearby analysis tool (Spatial API)          │
            └───────────────────────────────────────────────┘
```

## Component Details

### PostGIS Database (AWS RDS)
- Engine: PostgreSQL 16 with PostGIS
- Instance: db.t4g.micro (single-AZ, no Multi-AZ)
- Schema: `urban` with GiST spatial indexes
- Shared across Projects 01, 02, 03

### GeoServer
- Containerised (Docker)
- Workspace: `portfolio`
- Store: PostGIS connection to RDS
- Published layers: buildings, POIs, transit, parks, isochrones
- Protocols: WMS 1.1.1, WFS 2.0

### Spatial API (AWS Lambda)
- Runtime: Python 3.12
- Endpoints: /health, /pois/nearby, /facilities/nearest, /stats/area, /analysis/intersects
- Gateway: HTTP API (API Gateway v2)
- Connection: psycopg3 to RDS PostGIS

### Frontend (S3 + CloudFront)
- Mapbox GL JS v3.4
- Dark theme basemap with GIS overlays
- GeoJSON data loaded client-side
- GeoServer WMS/WFS for dynamic layers
- HTTPS via CloudFront

### ETL Pipeline
- CLI: `python -m src run --place "Amsterdam"`
- Stages: acquire → inspect → normalize → validate → repair → transform → export → report
- Exports: GeoJSON, GeoPackage, GeoParquet
- QA: HTML report with validation metrics

## CRS Strategy

| Context | CRS | EPSG | Reason |
|---------|-----|------|--------|
| Netherlands analysis | RD New | 28992 | National metric grid |
| Spain analysis | UTM 30N | 32630 | Metric for Valencia area |
| Web display | WGS84 | 4326 | Mapbox/GeoJSON standard |
| Tile services | Web Mercator | 3857 | Basemap alignment |
| Storage (PostGIS) | RD New | 28992 | Metric operations |

## Cost Estimate (Monthly)

| Resource | Estimated Cost |
|----------|---------------|
| RDS db.t4g.micro | ~$13 |
| S3 + CloudFront | ~$1-2 |
| Lambda (low traffic) | ~$0 (free tier) |
| API Gateway | ~$0 (free tier) |
| **Total** | **~$15/month** |
