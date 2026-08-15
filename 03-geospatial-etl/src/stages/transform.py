"""Transform stage, CRS transformation and metric calculations."""

from pathlib import Path

import geopandas as gpd


class TransformStage:
    def __init__(self, config, input_dir: Path, output_dir: Path):
        self.config = config
        self.input_dir = input_dir
        self.output_dir = output_dir

    def run(self) -> dict:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        results = {}

        for gpkg_file in sorted(self.input_dir.glob("*_normalized.gpkg")):
            name = gpkg_file.stem.replace("_normalized", "")
            print(f"    Transforming {name}...")

            gdf = gpd.read_file(gpkg_file)
            source_crs = str(gdf.crs)

            # Transform to target CRS
            if str(gdf.crs) != self.config.target_crs:
                gdf = gdf.to_crs(self.config.target_crs)

            # Add metric calculations for polygons
            if gdf.geometry.geom_type.isin(["Polygon", "MultiPolygon"]).any():
                poly_mask = gdf.geometry.geom_type.isin(["Polygon", "MultiPolygon"])
                gdf.loc[poly_mask, "area_sqm"] = gdf.loc[poly_mask].geometry.area

            # Add length for lines
            if gdf.geometry.geom_type.isin(["LineString", "MultiLineString"]).any():
                line_mask = gdf.geometry.geom_type.isin(["LineString", "MultiLineString"])
                gdf.loc[line_mask, "length_m"] = gdf.loc[line_mask].geometry.length

            outpath = self.output_dir / f"{name}.gpkg"
            gdf.to_file(outpath, driver="GPKG")

            results[name] = {
                "source_crs": source_crs,
                "target_crs": self.config.target_crs,
                "features": len(gdf),
            }

        return results
