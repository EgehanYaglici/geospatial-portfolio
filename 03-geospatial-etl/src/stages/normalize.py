"""Normalize stage, standardize schema and field names."""

from pathlib import Path

import geopandas as gpd
import pandas as pd


STANDARD_FIELDS = ["source_id", "name", "category", "subtype", "geometry", "source", "acquired_at"]


class NormalizeStage:
    def __init__(self, config, input_dir: Path, output_dir: Path):
        self.config = config
        self.input_dir = input_dir
        self.output_dir = output_dir

    def run(self) -> dict:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        results = {}

        for gpkg_file in sorted(self.input_dir.glob("*.gpkg")):
            name = gpkg_file.stem
            print(f"    Normalizing {name}...")

            gdf = gpd.read_file(gpkg_file)
            normalized = self._normalize_dataset(gdf, name)
            outpath = self.output_dir / f"{name}_normalized.gpkg"
            normalized.to_file(outpath, driver="GPKG")
            results[name] = {"input": len(gdf), "output": len(normalized)}

        return results

    def _normalize_dataset(self, gdf: gpd.GeoDataFrame, dataset_name: str) -> gpd.GeoDataFrame:
        """Standardize fields while preserving original attributes."""
        normalized = gpd.GeoDataFrame(geometry=gdf.geometry, crs=gdf.crs)

        # Source ID
        if "osmid" in gdf.columns:
            normalized["source_id"] = gdf["osmid"].astype(str)
        elif gdf.index.name == "osmid":
            normalized["source_id"] = gdf.index.astype(str)
        else:
            normalized["source_id"] = [f"{dataset_name}_{i}" for i in range(len(gdf))]

        # Name
        normalized["name"] = gdf.get("name", pd.Series([None] * len(gdf)))

        # Category and subtype based on dataset
        if dataset_name == "buildings":
            normalized["category"] = "building"
            normalized["subtype"] = gdf.get("building", "yes")
        elif dataset_name == "amenities":
            normalized["category"] = "amenity"
            normalized["subtype"] = gdf.get("amenity", None)
        elif dataset_name == "shops":
            normalized["category"] = "shop"
            normalized["subtype"] = gdf.get("shop", None)
        elif dataset_name == "transit":
            normalized["category"] = "transit"
            if "railway" in gdf.columns:
                normalized["subtype"] = gdf["railway"]
            elif "highway" in gdf.columns:
                normalized["subtype"] = gdf["highway"]
            else:
                normalized["subtype"] = None
        elif dataset_name == "parks":
            normalized["category"] = "park"
            normalized["subtype"] = gdf.get("leisure", "park")
        elif dataset_name == "water":
            normalized["category"] = "water"
            normalized["subtype"] = gdf.get("natural", "water")
        elif dataset_name == "roads":
            normalized["category"] = "road"
            normalized["subtype"] = gdf.get("highway", None)
        else:
            normalized["category"] = dataset_name
            normalized["subtype"] = None

        normalized["source"] = "osm"
        normalized["acquired_at"] = pd.Timestamp.now(tz="UTC").isoformat()

        return normalized
