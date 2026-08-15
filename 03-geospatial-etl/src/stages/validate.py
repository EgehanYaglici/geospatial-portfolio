"""Validate stage, check geometry validity, nulls, duplicates."""

import json
from pathlib import Path

import geopandas as gpd


class ValidateStage:
    def __init__(self, config, input_dir: Path):
        self.config = config
        self.input_dir = input_dir
        self.validation_results = {}

    def run(self) -> dict:
        for gpkg_file in sorted(self.input_dir.glob("*_normalized.gpkg")):
            name = gpkg_file.stem.replace("_normalized", "")
            print(f"    Validating {name}...")

            gdf = gpd.read_file(gpkg_file)
            issues = self._validate(gdf, name)
            self.validation_results[name] = issues

            total = sum(v for v in issues.values() if isinstance(v, int))
            if total > 0:
                print(f"      Issues found: {issues}")
            else:
                print(f"      Clean, no issues")

        return self.validation_results

    def _validate(self, gdf: gpd.GeoDataFrame, name: str) -> dict:
        null_geom = int(gdf.geometry.isna().sum())
        empty_geom = int(gdf.geometry.is_empty.sum()) if not gdf.geometry.isna().all() else 0
        invalid_geom = int((~gdf.geometry.is_valid).sum()) if not gdf.geometry.isna().all() else 0

        # Duplicate geometries (WKB comparison)
        if len(gdf) > 0 and not gdf.geometry.isna().all():
            wkb = gdf.geometry.apply(lambda g: g.wkb if g else None)
            dup_geom = int(wkb.duplicated().sum())
        else:
            dup_geom = 0

        # Duplicate source IDs
        dup_ids = int(gdf["source_id"].duplicated().sum()) if "source_id" in gdf.columns else 0

        # CRS check
        has_crs = gdf.crs is not None

        return {
            "total_features": len(gdf),
            "null_geometry": null_geom,
            "empty_geometry": empty_geom,
            "invalid_geometry": invalid_geom,
            "duplicate_geometry": dup_geom,
            "duplicate_ids": dup_ids,
            "has_crs": has_crs,
        }
