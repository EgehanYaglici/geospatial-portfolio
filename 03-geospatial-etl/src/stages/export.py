"""Export stage, produce GeoJSON, GeoPackage, and GeoParquet with benchmarks."""

import time
from pathlib import Path

import geopandas as gpd
import pandas as pd


class ExportStage:
    def __init__(self, config, input_dir: Path, output_dir: Path):
        self.config = config
        self.input_dir = input_dir
        self.output_dir = output_dir

    def run(self) -> dict:
        exports_dir = self.output_dir / "exports"
        exports_dir.mkdir(parents=True, exist_ok=True)
        results = {}
        benchmarks = []

        for gpkg_file in sorted(self.input_dir.glob("*.gpkg")):
            name = gpkg_file.stem
            print(f"    Exporting {name}...")

            gdf = gpd.read_file(gpkg_file)
            bench = self._export_formats(gdf, name, exports_dir)
            benchmarks.extend(bench)
            results[name] = {"formats": len(bench)}

        # Save benchmark results
        if benchmarks:
            bench_df = pd.DataFrame(benchmarks)
            bench_path = self.output_dir / "tables" / "format_benchmarks.csv"
            bench_path.parent.mkdir(parents=True, exist_ok=True)
            bench_df.to_csv(bench_path, index=False)
            results["benchmark_file"] = str(bench_path)

        return results

    def _export_formats(self, gdf: gpd.GeoDataFrame, name: str, output_dir: Path) -> list:
        benchmarks = []

        # GeoJSON
        geojson_path = output_dir / f"{name}.geojson"
        t0 = time.time()
        gdf.to_file(geojson_path, driver="GeoJSON")
        write_time = time.time() - t0
        t0 = time.time()
        _ = gpd.read_file(geojson_path)
        read_time = time.time() - t0
        benchmarks.append({
            "dataset": name,
            "format": "GeoJSON",
            "size_mb": round(geojson_path.stat().st_size / 1024 / 1024, 3),
            "write_time_s": round(write_time, 3),
            "read_time_s": round(read_time, 3),
        })

        # GeoPackage
        gpkg_path = output_dir / f"{name}.gpkg"
        t0 = time.time()
        gdf.to_file(gpkg_path, driver="GPKG")
        write_time = time.time() - t0
        t0 = time.time()
        _ = gpd.read_file(gpkg_path)
        read_time = time.time() - t0
        benchmarks.append({
            "dataset": name,
            "format": "GeoPackage",
            "size_mb": round(gpkg_path.stat().st_size / 1024 / 1024, 3),
            "write_time_s": round(write_time, 3),
            "read_time_s": round(read_time, 3),
        })

        # GeoParquet
        try:
            parquet_path = output_dir / f"{name}.parquet"
            t0 = time.time()
            gdf.to_parquet(parquet_path)
            write_time = time.time() - t0
            t0 = time.time()
            _ = gpd.read_parquet(parquet_path)
            read_time = time.time() - t0
            benchmarks.append({
                "dataset": name,
                "format": "GeoParquet",
                "size_mb": round(parquet_path.stat().st_size / 1024 / 1024, 3),
                "write_time_s": round(write_time, 3),
                "read_time_s": round(read_time, 3),
            })
        except Exception as e:
            print(f"      GeoParquet export failed for {name}: {e}")

        return benchmarks
