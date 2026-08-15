"""
Core ETL Pipeline orchestrator.
Executes stages sequentially: acquire → inspect → normalize → validate → repair → transform → export → report
"""

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .stages.acquire import AcquireStage
from .stages.inspect import InspectStage
from .stages.normalize import NormalizeStage
from .stages.validate import ValidateStage
from .stages.repair import RepairStage
from .stages.transform import TransformStage
from .stages.export import ExportStage
from .stages.report import ReportStage


@dataclass
class PipelineConfig:
    place: str
    upload_aws: bool = False
    load_postgis: bool = False
    base_dir: Path = field(default_factory=lambda: Path(__file__).parents[1])
    target_crs: str = "EPSG:28992"


class Pipeline:
    def __init__(self, place: str, upload_aws: bool = False, load_postgis: bool = False):
        self.config = PipelineConfig(
            place=place,
            upload_aws=upload_aws,
            load_postgis=load_postgis,
        )
        self.data_dir = self.config.base_dir / "data"
        self.raw_dir = self.data_dir / "raw"
        self.interim_dir = self.data_dir / "interim"
        self.processed_dir = self.data_dir / "processed"
        self.outputs_dir = self.config.base_dir / "outputs"
        self.metadata_dir = self.config.base_dir / "metadata"

        for d in [self.raw_dir, self.interim_dir, self.processed_dir,
                  self.outputs_dir, self.metadata_dir]:
            d.mkdir(parents=True, exist_ok=True)

        self.results = {}
        self.start_time = None

    def execute(self):
        """Run all pipeline stages."""
        self.start_time = time.time()

        print("=" * 70)
        print("  GEOSPATIAL ETL PIPELINE")
        print(f"  Place: {self.config.place}")
        print(f"  Target CRS: {self.config.target_crs}")
        print(f"  Started: {datetime.now(timezone.utc).isoformat()}")
        print("=" * 70)

        stages = [
            ("acquire", AcquireStage(self.config, self.raw_dir)),
            ("inspect", InspectStage(self.config, self.raw_dir, self.metadata_dir)),
            ("normalize", NormalizeStage(self.config, self.raw_dir, self.interim_dir)),
            ("validate", ValidateStage(self.config, self.interim_dir)),
            ("repair", RepairStage(self.config, self.interim_dir)),
            ("transform", TransformStage(self.config, self.interim_dir, self.processed_dir)),
            ("export", ExportStage(self.config, self.processed_dir, self.outputs_dir)),
            ("report", ReportStage(self.config, self.results, self.outputs_dir)),
        ]

        for name, stage in stages:
            print(f"\n{'─' * 70}")
            print(f"  STAGE: {name.upper()}")
            print(f"{'─' * 70}")
            t0 = time.time()
            try:
                result = stage.run()
                self.results[name] = {
                    "status": "success",
                    "duration_s": round(time.time() - t0, 2),
                    "data": result,
                }
                print(f"  ✓ {name} completed in {time.time()-t0:.1f}s")
            except Exception as e:
                self.results[name] = {
                    "status": "failed",
                    "duration_s": round(time.time() - t0, 2),
                    "error": str(e),
                }
                print(f"  ✗ {name} FAILED: {e}")

        total_time = time.time() - self.start_time
        print(f"\n{'=' * 70}")
        print(f"  PIPELINE COMPLETE, {total_time:.1f}s total")
        print(f"{'=' * 70}")

        # Save pipeline metadata
        self._save_run_metadata(total_time)

    def _save_run_metadata(self, total_time: float):
        meta = {
            "pipeline_run": datetime.now(timezone.utc).isoformat(),
            "place": self.config.place,
            "target_crs": self.config.target_crs,
            "total_duration_s": round(total_time, 2),
            "stages": self.results,
        }
        with open(self.metadata_dir / "pipeline_run.json", "w") as f:
            json.dump(meta, f, indent=2, default=str)
