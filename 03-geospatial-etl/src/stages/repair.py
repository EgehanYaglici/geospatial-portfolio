"""Repair stage, fix invalid geometries using buffer(0) and make_valid."""

from pathlib import Path

import geopandas as gpd
from shapely.validation import make_valid


class RepairStage:
    def __init__(self, config, data_dir: Path):
        self.config = config
        self.data_dir = data_dir

    def run(self) -> dict:
        results = {}

        for gpkg_file in sorted(self.data_dir.glob("*_normalized.gpkg")):
            name = gpkg_file.stem.replace("_normalized", "")
            print(f"    Repairing {name}...")

            gdf = gpd.read_file(gpkg_file)
            repaired, stats = self._repair(gdf)

            # Overwrite with repaired version
            repaired.to_file(gpkg_file, driver="GPKG")
            results[name] = stats

            if stats["repaired"] > 0:
                print(f"      Repaired {stats['repaired']}/{stats['found_invalid']} invalid")
            else:
                print(f"      No repairs needed")

        return results

    def _repair(self, gdf: gpd.GeoDataFrame) -> tuple:
        invalid_mask = ~gdf.geometry.is_valid & ~gdf.geometry.isna()
        found = int(invalid_mask.sum())
        repaired = 0
        unrepairable = 0

        if found > 0:
            for idx in gdf.index[invalid_mask]:
                try:
                    fixed = make_valid(gdf.at[idx, "geometry"])
                    if fixed.is_valid and not fixed.is_empty:
                        gdf.at[idx, "geometry"] = fixed
                        repaired += 1
                    else:
                        unrepairable += 1
                except Exception:
                    unrepairable += 1

        # Remove null/empty geometries
        null_removed = int(gdf.geometry.isna().sum())
        gdf = gdf[~gdf.geometry.isna() & ~gdf.geometry.is_empty].copy()

        stats = {
            "found_invalid": found,
            "repaired": repaired,
            "unrepairable": unrepairable,
            "null_removed": null_removed,
            "final_count": len(gdf),
        }
        return gdf, stats
