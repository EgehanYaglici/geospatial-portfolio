"""Inspect stage, analyze raw data properties."""

import json
from pathlib import Path

import geopandas as gpd


class InspectStage:
    def __init__(self, config, input_dir: Path, metadata_dir: Path):
        self.config = config
        self.input_dir = input_dir
        self.metadata_dir = metadata_dir

    def run(self) -> dict:
        results = {}

        for gpkg_file in sorted(self.input_dir.glob("*.gpkg")):
            name = gpkg_file.stem
            print(f"    Inspecting {name}...")

            gdf = gpd.read_file(gpkg_file)
            geom_types = gdf.geometry.geom_type.value_counts().to_dict()
            bbox = gdf.total_bounds.tolist()
            null_geom = int(gdf.geometry.isna().sum())
            invalid_geom = int((~gdf.geometry.is_valid).sum())

            info = {
                "file": gpkg_file.name,
                "crs": str(gdf.crs),
                "feature_count": len(gdf),
                "geometry_types": geom_types,
                "bounding_box": bbox,
                "null_geometry": null_geom,
                "invalid_geometry": invalid_geom,
                "columns": list(gdf.columns),
                "size_mb": round(gpkg_file.stat().st_size / 1024 / 1024, 2),
            }
            results[name] = info
            print(f"      {len(gdf)} features, CRS={gdf.crs}, invalid={invalid_geom}")

        with open(self.metadata_dir / "inspection_report.json", "w") as f:
            json.dump(results, f, indent=2)

        return results
