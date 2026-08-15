# Geospatial Engineering Portfolio

**Egehan Yaglici**, GIS · Spatial Data Engineering · Web Mapping · Earth Observation

Seven case studies demonstrating end-to-end geospatial workflows from data acquisition through cloud deployment.

## Projects

| # | Project | Stack | Status |
|---|---------|-------|--------|
| 01 | [Cloud Urban GIS](01-cloud-urban-gis/) | PostGIS · GeoServer · AWS · Mapbox GL JS | Complete |
| 02 | [Serverless Spatial API](02-spatial-api/) | Lambda · API Gateway · Spatial SQL | Complete |
| 03 | [Geospatial ETL & QA](03-geospatial-etl/) | Python · GeoPandas · S3 · PostGIS | Complete |
| 04 | [Rotterdam Elevation](04-rotterdam-elevation/) | AHN · Raster Analysis · 3D Mapping | Complete |
| 05 | [Sentinel-1 SAR](05-sentinel1-sar/) | STAC · SAR · Change Detection | Complete |

## Architecture

```
                  OpenStreetMap / AHN / Copernicus
                            |
                            v
                     Python ETL Pipeline
                            |
                 +----------+----------+
                 |                     |
                 v                     v
              AWS S3               PostGIS (RDS)
           raw/processed               |
                                       |
                          +------------+------------+
                          |                         |
                          v                         v
                     GeoServer                  Lambda
                      WMS/WFS               Spatial API
                          |                         |
                          +-----------+-------------+
                                      |
                                      v
                              Mapbox GL JS
                                      |
                                      v
                             S3 + CloudFront
```

## Quick Start

```bash
# Create virtual environment
python -m venv .venv
source .venv/bin/activate
pip install -e .

# Run Amsterdam data acquisition
python 01-cloud-urban-gis/src/acquisition/acquire_amsterdam.py

# Run accessibility analysis
python 01-cloud-urban-gis/src/analysis/accessibility.py

# Run ETL pipeline
cd 03-geospatial-etl && python -m src run --place "Amsterdam, Netherlands"

# Run Rotterdam elevation analysis
python 04-rotterdam-elevation/src/acquisition/acquire_ahn.py
python 04-rotterdam-elevation/src/processing/elevation_analysis.py

# Run SAR analysis
python 05-sentinel1-sar/src/acquisition/discover_scenes.py
python 05-sentinel1-sar/src/processing/sar_analysis.py
```

## Requirements

- Python 3.12+
- PostgreSQL with PostGIS (local Docker or AWS RDS)
- AWS account (for deployment)
- Mapbox account (public token for frontend)

## AWS Deployment

Infrastructure is defined in `infrastructure/terraform/`.

```bash
cd infrastructure/terraform
terraform init
terraform plan -var="db_password=YOUR_PASSWORD"
terraform apply -var="db_password=YOUR_PASSWORD"
```

See [COST_NOTES.md](COST_NOTES.md) for estimated costs.

## Credentials

Copy `.env.example` to `.env` and fill in values. Never commit `.env`.
