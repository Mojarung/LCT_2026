"""Run a local experiment and append its provenance/result to the research journal.

Usage: python tools/record_experiment.py ID -- COMMAND [ARG ...]
No shell interpretation. Raw logs remain local; source/customer files are never uploaded.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import platform
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JOURNAL = ROOT / "docs/research/verified-pipeline/experiments.jsonl"


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def main() -> int:
    if len(sys.argv) < 4 or sys.argv[2] != "--":
        raise SystemExit(__doc__)
    name, command = sys.argv[1], sys.argv[3:]
    if not name or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789-_" for c in name):
        raise SystemExit("ID must contain only lowercase letters, digits, dash or underscore")
    started = datetime.now(UTC)
    stamp = started.strftime("%Y%m%dT%H%M%S%fZ")
    log = ROOT / "out/experiments" / f"{stamp}-{name}.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    packages = {}
    for package in ("pytest", "ezdxf", "shapely", "scipy", "numpy"):
        try:
            packages[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            packages[package] = None
    fingerprint = hashlib.sha256(
        git("diff", "HEAD", "--", "src", "tests", "config", "tools").encode()
    )
    for path in sorted(
        git(
            "ls-files", "--others", "--exclude-standard", "src", "tests", "config", "tools"
        ).splitlines()
    ):
        fingerprint.update(path.encode())
        fingerprint.update((ROOT / path).read_bytes())
    record = {
        "id": name,
        "started_utc": started.isoformat(),
        "command": command,
        "head": git("rev-parse", "HEAD"),
        "branch": git("branch", "--show-current"),
        "code_diff_sha256": fingerprint.hexdigest(),
        "python": sys.version,
        "platform": platform.platform(),
        "packages": packages,
        "log": str(log.relative_to(ROOT)),
    }
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src"), "PYTHONHASHSEED": "0"}
    begin = time.perf_counter()
    with log.open("w") as stream:
        result = subprocess.run(
            command, cwd=ROOT, env=env, stdout=stream, stderr=subprocess.STDOUT, check=False
        )
    record.update(exit_code=result.returncode, duration_s=round(time.perf_counter() - begin, 3))
    output = log.read_text(errors="replace")
    record["output_sha256"] = hashlib.sha256(log.read_bytes()).hexdigest()
    # A short result tail is useful for test summaries, without persisting full source data.
    print(output[-12000:])
    with JOURNAL.open("a") as stream:
        stream.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(json.dumps(record, ensure_ascii=False, indent=2))
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
