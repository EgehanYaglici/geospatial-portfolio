"""Report stage, generate QA report in HTML, JSON, and CSV."""

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


class ReportStage:
    def __init__(self, config, pipeline_results: dict, output_dir: Path):
        self.config = config
        self.results = pipeline_results
        self.output_dir = output_dir

    def run(self) -> dict:
        reports_dir = self.output_dir / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)

        report_data = self._compile_report()

        # JSON report
        with open(reports_dir / "qa_report.json", "w") as f:
            json.dump(report_data, f, indent=2, default=str)

        # CSV summary
        summary_rows = self._create_summary_rows(report_data)
        if summary_rows:
            df = pd.DataFrame(summary_rows)
            df.to_csv(reports_dir / "qa_summary.csv", index=False)

        # HTML report
        html = self._generate_html(report_data, summary_rows)
        with open(reports_dir / "qa_report.html", "w") as f:
            f.write(html)

        return {"report_dir": str(reports_dir)}

    def _compile_report(self) -> dict:
        return {
            "generated": datetime.now(timezone.utc).isoformat(),
            "place": self.config.place,
            "target_crs": self.config.target_crs,
            "stages": self.results,
        }

    def _create_summary_rows(self, report_data: dict) -> list:
        rows = []
        inspect_data = self.results.get("inspect", {}).get("data", {})
        validate_data = self.results.get("validate", {}).get("data", {})
        repair_data = self.results.get("repair", {}).get("data", {})

        for name in inspect_data:
            insp = inspect_data.get(name, {})
            val = validate_data.get(name, {})
            rep = repair_data.get(name, {})
            rows.append({
                "dataset": name,
                "input_features": insp.get("feature_count", 0),
                "output_features": rep.get("final_count", insp.get("feature_count", 0)),
                "invalid_geometry": val.get("invalid_geometry", 0),
                "repaired": rep.get("repaired", 0),
                "duplicates": val.get("duplicate_geometry", 0),
                "crs": insp.get("crs", "unknown"),
                "size_mb": insp.get("size_mb", 0),
            })
        return rows

    def _generate_html(self, report_data: dict, summary_rows: list) -> str:
        rows_html = ""
        for row in summary_rows:
            rows_html += f"""<tr>
                <td>{row['dataset']}</td>
                <td>{row['input_features']:,}</td>
                <td>{row['output_features']:,}</td>
                <td>{row['invalid_geometry']}</td>
                <td>{row['repaired']}</td>
                <td>{row['duplicates']}</td>
                <td>{row['crs']}</td>
                <td>{row['size_mb']:.2f}</td>
            </tr>"""

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Geospatial ETL, QA Report</title>
    <style>
        body {{ font-family: 'Inter', system-ui, sans-serif; max-width: 1000px; margin: 2rem auto; padding: 0 1rem; color: #1a1a2e; }}
        h1 {{ color: #16213e; border-bottom: 3px solid #0f3460; padding-bottom: 0.5rem; }}
        h2 {{ color: #0f3460; margin-top: 2rem; }}
        table {{ border-collapse: collapse; width: 100%; margin: 1rem 0; }}
        th, td {{ border: 1px solid #ddd; padding: 8px 12px; text-align: left; }}
        th {{ background: #0f3460; color: white; }}
        tr:nth-child(even) {{ background: #f8f9fa; }}
        .meta {{ color: #666; font-size: 0.9rem; }}
        .badge {{ display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 0.8rem; }}
        .badge-ok {{ background: #d4edda; color: #155724; }}
        .badge-warn {{ background: #fff3cd; color: #856404; }}
    </style>
</head>
<body>
    <h1>Geospatial ETL, QA Report</h1>
    <p class="meta">Generated: {report_data['generated']}<br>
    Place: {report_data['place']}<br>
    Target CRS: {report_data['target_crs']}</p>

    <h2>Dataset Summary</h2>
    <table>
        <thead>
            <tr>
                <th>Dataset</th>
                <th>Input</th>
                <th>Output</th>
                <th>Invalid</th>
                <th>Repaired</th>
                <th>Duplicates</th>
                <th>CRS</th>
                <th>Size (MB)</th>
            </tr>
        </thead>
        <tbody>
            {rows_html}
        </tbody>
    </table>

    <h2>Pipeline Stages</h2>
    <table>
        <thead><tr><th>Stage</th><th>Status</th><th>Duration (s)</th></tr></thead>
        <tbody>
            {"".join(f'<tr><td>{k}</td><td><span class="badge badge-ok">{v.get("status", "n/a")}</span></td><td>{v.get("duration_s", "n/a")}</td></tr>' for k, v in report_data.get("stages", {}).items())}
        </tbody>
    </table>
</body>
</html>"""
