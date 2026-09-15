"""Запись артефактов: plan.json, interpretations.csv/json, run_manifest.json, verify.json."""

from __future__ import annotations

import csv
import platform
from dataclasses import asdict
from importlib.metadata import PackageNotFoundError, version
from typing import TYPE_CHECKING, Any

import orjson

from green.domain.planting import Placement

if TYPE_CHECKING:
    from pathlib import Path

    from green.application.results import RunReport
    from green.domain.norms import RuleBook
    from green.domain.planting import Explanation, Plan, Rejection, RuleCheck

CSV_COLUMNS = (
    "kind",
    "number",
    "subject_id",
    "planting_type",
    "species_ru",
    "species_lat",
    "x",
    "y",
    "verdict",
    "rule_id",
    "outcome",
    "measured_m",
    "threshold_m",
    "object_class",
    "nearest_ref",
    "act_id",
    "act_title",
    "clause",
    "related",
    "citation_status",
    "quote",
    "url",
    "explanation",
)
_PACKAGES = ("green", "ezdxf", "shapely", "fastapi", "pydantic")


class FileArtifactSink:
    def save(self, directory: Path, report: RunReport) -> dict[str, Path]:
        directory.mkdir(parents=True, exist_ok=True)
        rows = build_rows(report.plan, report.rulebook)
        return {
            "result.dxf": report.output_dxf,
            "plan.json": _write_json(directory / "plan.json", _plan(report)),
            "interpretations.json": _write_json(directory / "interpretations.json", rows),
            "interpretations.csv": _write_csv(directory / "interpretations.csv", rows),
            "run_manifest.json": _write_json(directory / "run_manifest.json", _manifest(report)),
            "verify.json": _write_json(directory / "verify.json", _integrity(report)),
            "layers_report.json": _write_json(directory / "layers_report.json", _layers(report)),
        }


def build_rows(plan: Plan, rulebook: RuleBook) -> list[dict[str, Any]]:
    """Одна строка на пару (решение, правило): эксперт фильтрует по номеру посадки или отказа."""
    texts = {e.subject_id: e for e in plan.explanations}
    rows: list[dict[str, Any]] = []
    for placement in plan.placements:
        rows += _rows(placement, placement.checks, texts.get(placement.placement_id), rulebook)
    for rejection in plan.rejections:
        rows += _rows(rejection, rejection.blocking, texts.get(rejection.rejection_id), rulebook)
    return rows


def _rows(
    subject: Placement | Rejection,
    checks: tuple[RuleCheck, ...],
    explanation: Explanation | None,
    rulebook: RuleBook,
) -> list[dict[str, Any]]:
    if isinstance(subject, Placement):
        head = {
            "kind": "placement",
            "subject_id": subject.placement_id,
            "species_ru": subject.species.name_ru,
            "species_lat": subject.species.name_lat,
        }
    else:
        head = {
            "kind": "rejection",
            "subject_id": subject.rejection_id,
            "species_ru": "",
            "species_lat": "",
        }
    base = {
        **head,
        "number": subject.number,
        "planting_type": subject.planting_type.value,
        "x": subject.x,
        "y": subject.y,
        "verdict": subject.verdict.value,
        "explanation": explanation.text if explanation else "",
    }
    rows = []
    for check in checks:
        rule = rulebook.rule(check.rule_id)
        citation = rule.citation if rule else None
        act = rulebook.act_of(citation) if citation else None
        rows.append(
            {
                **base,
                **_check(check),
                "act_id": citation.act_id if citation else "",
                "act_title": act.title if act else "",
                "clause": citation.clause if citation else "",
                "related": "; ".join(
                    f"{rulebook.label_of(ref.act_id)}, {ref.clause}"
                    for ref in (citation.related if citation else ())
                ),
                "citation_status": citation.status.value if citation else "",
                "quote": citation.quote if citation else "",
                "url": act.url if act else "",
            }
        )
    return rows


def _check(check: RuleCheck) -> dict[str, Any]:
    return {
        "rule_id": check.rule_id,
        "outcome": check.outcome.value,
        "measured_m": check.measured_m,
        "threshold_m": check.threshold_m,
        "object_class": check.object_class.value if check.object_class else None,
        "nearest_ref": str(check.nearest) if check.nearest else None,
    }


def _source(report: RunReport) -> dict[str, Any]:
    return {
        "name": report.source_name,
        "sha256": report.source_sha256,
        "dxf_version": report.dxf_version,
    }


def _plan(report: RunReport) -> dict[str, Any]:
    plan = report.plan
    texts = {e.subject_id: e.text for e in plan.explanations}
    return {
        "run_id": report.run_id,
        "source": _source(report),
        "summary": report.summary(),
        "placements": [
            {
                "id": p.placement_id,
                "number": p.number,
                "planting_type": p.planting_type.value,
                "species": asdict(p.species),
                "x": p.x,
                "y": p.y,
                "verdict": p.verdict.value,
                "explanation": texts.get(p.placement_id, ""),
                "checks": [_check(c) for c in p.checks],
            }
            for p in plan.placements
        ],
        "rejections": [
            {
                "id": r.rejection_id,
                "number": r.number,
                "planting_type": r.planting_type.value,
                "x": r.x,
                "y": r.y,
                "verdict": r.verdict.value,
                "explanation": texts.get(r.rejection_id, ""),
                "blocking": [_check(c) for c in r.blocking],
            }
            for r in plan.rejections
        ],
        "warnings": list(report.warnings),
    }


def _manifest(report: RunReport) -> dict[str, Any]:
    rulebook = report.rulebook
    rules = (*rulebook.distance_rules, *rulebook.species_bans)
    return {
        "run_id": report.run_id,
        "source": _source(report),
        "converter": report.converter,
        "profile": report.profile,
        "params": asdict(report.params),
        "fingerprints": {"rules": rulebook.fingerprint, "layer_map": report.layer_map_fingerprint},
        "rules": {"total": len(rules), "verified": sum(r.citation.is_verified for r in rules)},
        "versions": {
            "python": platform.python_version(),
            **{name: _version(name) for name in _PACKAGES},
        },
        "timings_ms": {t.stage: t.ms for t in report.timings},
        "summary": report.summary(),
    }


def _integrity(report: RunReport) -> dict[str, Any]:
    integrity = report.integrity
    return {
        "ok": integrity.ok,
        "source_entities": integrity.source_entities,
        "unchanged": integrity.unchanged,
        "changed": list(integrity.changed),
        "missing": list(integrity.missing),
        "added_outside_result_layers": list(integrity.added_outside_result_layers),
    }


def _layers(report: RunReport) -> dict[str, Any]:
    return {
        "class_counts": dict(report.class_counts),
        "layers": [
            {"layer": c.layer, "object_class": c.object_class.value, "features": c.features}
            for c in report.coverage
        ],
    }


def _write_json(path: Path, payload: object) -> Path:
    path.write_bytes(orjson.dumps(payload, option=orjson.OPT_INDENT_2 | orjson.OPT_NON_STR_KEYS))
    return path


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> Path:
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(
            stream, fieldnames=CSV_COLUMNS, delimiter=";", extrasaction="ignore"
        )
        writer.writeheader()
        writer.writerows(rows)
    return path


def _version(name: str) -> str | None:
    try:
        return version(name)
    except PackageNotFoundError:
        return None
