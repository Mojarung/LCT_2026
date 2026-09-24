"""Compare baseline and current reader on exactly the same converted DXF."""

# ruff: noqa: INP001, T201 - standalone research driver prints aggregate results

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory


def _run(
    source: Path, config: Path, out: Path, baseline_file: Path | None, region_file: Path | None
) -> dict:
    command = [
        sys.executable,
        "tools/benchmark_region_polygon.py",
        "--source",
        str(source),
        "--config",
        str(config),
        "--out",
        str(out),
        "--read-only",
    ]
    if baseline_file is not None:
        command.extend(("--reader-file", str(baseline_file)))
        if region_file is not None:
            command.extend(("--region-module-file", str(region_file)))
    completed = subprocess.run(command, capture_output=True, text=True, check=True)  # noqa: S603
    return json.loads(completed.stdout)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--baseline-revision", required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("--repeats must be positive")
    args.out.mkdir(parents=True, exist_ok=True)
    source_hash = hashlib.sha256(args.source.read_bytes()).hexdigest()
    revision = args.baseline_revision
    baseline_source = subprocess.run(  # noqa: S603 - fixed git argv
        ["git", "show", f"{revision}:src/green/infrastructure/cad/reader.py"],  # noqa: S607
        capture_output=True,
        check=True,
    ).stdout
    region_source = subprocess.run(  # noqa: S603 - fixed git argv
        ["git", "show", f"{revision}:src/green/infrastructure/cad/region_geometry.py"],  # noqa: S607
        capture_output=True,
        check=False,
    )
    with TemporaryDirectory(prefix="reader_baseline_") as temporary:
        baseline_file = Path(temporary) / "reader.py"
        baseline_file.write_bytes(baseline_source)
        region_file = None
        if region_source.returncode == 0:
            region_file = Path(temporary) / "region_geometry.py"
            region_file.write_bytes(region_source.stdout)
        runs: dict[str, list[dict]] = {"baseline": [], "current": []}
        for index in range(args.repeats):
            for name, reader_file, saved_region in (
                ("baseline", baseline_file, region_file),
                ("current", None, None),
            ):
                measurement = _run(
                    args.source,
                    args.config,
                    args.out / f"{name}-{index}",
                    reader_file,
                    saved_region,
                )
                measurement.pop("reader_file", None)
                runs[name].append(measurement)
    result = {
        "source_sha256": source_hash,
        "baseline_revision": revision,
        "baseline_reader_sha256": hashlib.sha256(baseline_source).hexdigest(),
        "baseline_region_sha256": hashlib.sha256(region_source.stdout).hexdigest()
        if region_file is not None
        else None,
        "repeats_per_version": args.repeats,
        "summary": {
            name: {
                "region_features": series[0]["region_features"],
                "region_gaps": series[0]["region_gaps"],
                "all_geometry_gaps": series[0]["all_geometry_gaps"],
                "median_read_s": statistics.median(row["read_s"] for row in series),
                "median_peak_rss_mb": statistics.median(row["peak_rss_mb"] for row in series),
            }
            for name, series in runs.items()
        },
        "runs": runs,
    }
    output = args.report
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result["summary"], ensure_ascii=False))


if __name__ == "__main__":
    main()
