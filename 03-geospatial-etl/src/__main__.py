"""
Automated Geospatial ETL Pipeline
Usage: python -m src run --place "Amsterdam, Netherlands"
"""

import argparse
import sys
from pathlib import Path

from .pipeline import Pipeline


def main():
    parser = argparse.ArgumentParser(
        prog="geospatial-etl",
        description="Automated Cloud Geospatial ETL & QA Pipeline",
    )
    subparsers = parser.add_subparsers(dest="command")

    run_parser = subparsers.add_parser("run", help="Run the full ETL pipeline")
    run_parser.add_argument("--place", required=True, help="OSM place query")
    run_parser.add_argument("--upload-aws", action="store_true", help="Upload to S3")
    run_parser.add_argument("--load-postgis", action="store_true", help="Load to PostGIS")

    args = parser.parse_args()

    if args.command == "run":
        pipeline = Pipeline(
            place=args.place,
            upload_aws=args.upload_aws,
            load_postgis=args.load_postgis,
        )
        pipeline.execute()
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
