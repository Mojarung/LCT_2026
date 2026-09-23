"""Fresh read survey of locally selected coverage plans; no private geometry in results.

Usage: python tools/survey_covering_inputs.py JSON_LIST_OF_LOCAL_PATHS
Selection is recorded in the research findings. Results are input diagnostics,
not a complete-package or semantic-accuracy benchmark.
"""
# ruff: noqa: INP001, T201 - standalone research driver

from __future__ import annotations

import json
import sys
from pathlib import Path

from survey_cad_inputs import ROOT, survey


def main() -> None:
    selected = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    target = ROOT / "docs/research/verified-pipeline/coverage_input_survey.json"
    rows = []
    for source in selected:
        row = survey(Path(source))
        rows.append(row)
        target.write_text(
            json.dumps(
                {
                    "scope": "Selected material plans, fresh conversion/read only. "
                    "No inferred ground truth or full-package certification.",
                    "rows": rows,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        print(
            {k: v for k, v in row.items() if k not in {"warnings", "read_diagnostics"}}, flush=True
        )


if __name__ == "__main__":
    main()
