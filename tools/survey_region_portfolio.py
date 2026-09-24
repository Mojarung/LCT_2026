"""Classify REGION payload loss across the fixed 15-file DWG import sample."""

# ruff: noqa: INP001, T201 - standalone research driver prints aggregate counts

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath

from survey_region_acds import survey


def _source(row: dict[str, object], catalog: list[dict[str, object]], root: Path) -> Path:
    matches = []
    for candidate in catalog:
        relative = candidate.get("file")
        if not isinstance(relative, str) or PurePosixPath(relative).name != row["name"]:
            continue
        if candidate.get("size") != row["bytes"] or "/PaxHeader/" in f"/{relative}/":
            continue
        path = root / relative
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if digest == row["source_sha256"]:
            matches.append(path)
    if not matches:
        raise FileNotFoundError(f"No matching source for {row['source_sha256']}")
    return matches[0]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--converted-root", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.work_dir.mkdir(parents=True, exist_ok=True)
    catalog = [json.loads(line) for line in args.catalog.read_text().splitlines()]
    selected = [
        row
        for row in json.loads(args.sample.read_bytes())["rows"]
        if row.get("read_diagnostics", {}).get("skipped_by_type", {}).get("REGION", 0)
    ]
    results = []
    for row in selected:
        source = _source(row, catalog, args.dataset_root)
        converted = args.converted_root / row["source_sha256"][:20] / source.with_suffix(
            ".dxf"
        ).name
        result = survey(source, converted, args.work_dir)
        result.update(street=row["street"], source_name=row["name"])
        results.append(result)
        args.output.write_text(
            json.dumps(
                {
                    "scope": (
                        "Fixed E14 REGION subset. Flags and payload presence only; no proof of "
                        "accurate contours or recoverability. Raw CAD and LibreDWG JSON "
                        "are not saved."
                    ),
                    "rows": results,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n"
        )
        print(
            json.dumps(
                {
                    "street": row["street"],
                    "source_region_count": result["source_region_count"],
                    "converted_sat": result["converted_region_sat_count"],
                    "converted_sab": result["converted_region_sab_count"],
                    "source_flags": result["region_flag_counts"],
                },
                ensure_ascii=False,
            ),
            flush=True,
        )


if __name__ == "__main__":
    main()
