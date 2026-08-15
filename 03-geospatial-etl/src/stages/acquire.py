"""Acquire stage, download OSM data for the specified place."""

import json
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import osmnx as ox


class AcquireStage:
    def __init__(self, config, output_dir: Path):
        self.config = config
        self.output_dir = output_dir

    def run(self) -> dict:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        results = {}

        datasets = {
            "boundary": lambda: ox.geocode_to_gdf(self.config.place),
            "buildings": lambda: ox.features_from_place(
                self.config.place, tags={"building": True}
            ),
            "roads": lambda: ox.graph_to_gdfs(
                ox.graph_from_place(self.config.place, network_type="drive")
            )[1],
            "amenities": lambda: ox.features_from_place(
                self.config.place,
                tags={"amenity": ["restaurant", "cafe", "hospital", "pharmacy",
                                  "school", "university", "fuel", "parking"]},
            ),
            "shops": lambda: ox.features_from_place(
                self.config.place, tags={"shop": "supermarket"}
            ),
            "transit": lambda: ox.features_from_place(
                self.config.place,
                tags={"railway": ["station", "halt", "tram_stop"], "highway": "bus_stop"},
            ),
            "parks": lambda: ox.features_from_place(
                self.config.place, tags={"leisure": "park"}
            ),
            "water": lambda: ox.features_from_place(
                self.config.place, tags={"natural": "water"}
            ),
        }

        for name, fetcher in datasets.items():
            print(f"    Acquiring {name}...")
            try:
                gdf = fetcher()
                outpath = self.output_dir / f"{name}.gpkg"
                gdf.to_file(outpath, driver="GPKG")
                results[name] = {
                    "features": len(gdf),
                    "file": str(outpath),
                    "crs": str(gdf.crs),
                }
            except Exception as e:
                print(f"      Warning: {name} failed, {e}")
                results[name] = {"features": 0, "error": str(e)}

        # Save acquisition metadata
        meta = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "OpenStreetMap via OSMnx",
            "place": self.config.place,
            "datasets": results,
        }
        with open(self.output_dir / "acquisition_metadata.json", "w") as f:
            json.dump(meta, f, indent=2)

        return results
