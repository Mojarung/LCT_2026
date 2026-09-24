"""Diagnose whether LibreDWG drops external ACIS data from a DWG REGION.

Only aggregate flags and hashes are printed. The temporary LibreDWG JSON and
customer geometry are kept out of Git and removed when the survey finishes.
"""

# ruff: noqa: INP001, T201 - standalone diagnostic prints one JSON summary

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from collections import Counter
from pathlib import Path
from tempfile import TemporaryDirectory

import ezdxf
from ezdxf.entities import Region


def survey(source: Path, converted: Path | None, work_dir: Path) -> dict[str, object]:
    source_bytes = source.read_bytes()
    with TemporaryDirectory(prefix="region_acds_", dir=work_dir) as temporary:
        raw_json = Path(temporary) / "raw.json"
        command = ["dwgread", "-O", "minJSON", "-o", str(raw_json), str(source)]
        completed = subprocess.run(  # noqa: S603 - fixed executable, path passed as argv
            command, capture_output=True, timeout=120, check=False
        )
        if completed.returncode != 0:
            raise RuntimeError(f"dwgread failed with exit code {completed.returncode}")
        raw = json.loads(raw_json.read_bytes())
    regions = [
        entity
        for entity in raw.get("OBJECTS", ())
        if entity.get("entity") == "REGION"
    ]
    flags = Counter(
        (
            bool(region.get("has_ds_data")),
            bool(region.get("acis_empty")),
            bool(region.get("wireframe_data_present")),
        )
        for region in regions
    )
    acds = raw.get("AcDs", {})
    result: dict[str, object] = {
        "source_sha256": hashlib.sha256(source_bytes).hexdigest(),
        "source_bytes": len(source_bytes),
        "source_region_count": len(regions),
        "source_acds_marker_present": b"AcDb:AcDsPrototype_1b" in source_bytes,
        "dwgread_acds_header": {
            key: acds.get(key)
            for key in ("file_signature", "version", "ds_version", "file_size")
            if key in acds
        },
        "region_flag_counts": [
            {
                "has_ds_data": has_ds_data,
                "acis_empty": acis_empty,
                "wireframe_data_present": wireframe_data_present,
                "count": count,
            }
            for (has_ds_data, acis_empty, wireframe_data_present), count in sorted(flags.items())
        ],
    }
    if converted is not None:
        doc = ezdxf.readfile(converted)
        converted_regions = [
            entity for entity in doc.entitydb.values() if isinstance(entity, Region)
        ]
        result.update(
            converted_sha256=hashlib.sha256(converted.read_bytes()).hexdigest(),
            converted_region_count=len(converted_regions),
            converted_region_sat_count=sum(bool(region.sat) for region in converted_regions),
            converted_region_sab_count=sum(bool(region.sab) for region in converted_regions),
            converted_acds_records=bool(doc.acdsdata.has_records),
        )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--converted", type=Path)
    parser.add_argument("--work-dir", type=Path, required=True)
    args = parser.parse_args()
    args.work_dir.mkdir(parents=True, exist_ok=True)
    print(
        json.dumps(survey(args.source, args.converted, args.work_dir), ensure_ascii=False, indent=2)
    )


if __name__ == "__main__":
    main()
