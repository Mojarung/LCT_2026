"""Артефакты нормоконтроля: audit.json, audit.csv, audit.md, verify.json."""

from __future__ import annotations

import csv
from typing import TYPE_CHECKING, Any

import orjson

from green.application.explain import describe_check

if TYPE_CHECKING:
    from pathlib import Path

    from green.application.audit import AuditedPlanting, AuditReport
    from green.domain.norms import RuleBook
    from green.domain.planting import RuleCheck

CSV_COLUMNS = (
    "number",
    "planting_type",
    "type_basis",
    "layer",
    "x",
    "y",
    "crown_m",
    "verdict",
    "rule_id",
    "outcome",
    "measured_m",
    "threshold_m",
    "shortfall_m",
    "object_class",
    "nearest_ref",
    "act_id",
    "act_title",
    "clause",
    "quote",
    "url",
    "text",
)
_REPORTED = frozenset({"fail", "barrier", "no_data"})
_WORST_IN_REPORT = 20


class AuditArtifactSink:
    def save(self, directory: Path, report: AuditReport) -> dict[str, Path]:
        directory.mkdir(parents=True, exist_ok=True)
        rows = [row for p in report.plantings for row in _rows(p, report.rulebook)]
        return {
            report.output_dxf.name: report.output_dxf,
            "audit.json": _write_json(directory / "audit.json", _document(report)),
            "audit.csv": _write_csv(directory / "audit.csv", rows),
            "audit.md": _write_text(directory / "audit.md", _markdown(report)),
            "verify.json": _write_json(
                directory / "verify.json",
                {
                    "ok": report.integrity.ok,
                    "source_entities": report.integrity.source_entities,
                    "unchanged": report.integrity.unchanged,
                    "changed": list(report.integrity.changed),
                    "missing": list(report.integrity.missing),
                    "added_outside_result_layers": list(
                        report.integrity.added_outside_result_layers
                    ),
                    "unexportable": report.integrity.unexportable,
                },
            ),
        }


def _document(report: AuditReport) -> dict[str, Any]:
    return {
        "run_id": report.run_id,
        "source_name": report.source_name,
        "source_sha256": report.source_sha256,
        "profile": report.profile,
        "planting_layers": report.planting_layers,
        "rulebook_fingerprint": report.rulebook.fingerprint,
        "summary": report.summary(),
        "timings_ms": {t.stage: t.ms for t in report.timings},
        "plantings": [_planting(p, report.rulebook) for p in report.plantings],
    }


def _planting(planting: AuditedPlanting, rulebook: RuleBook) -> dict[str, Any]:
    return {
        "number": planting.number,
        "planting_type": planting.planting_type.value,
        "type_basis": planting.type_basis,
        "layer": planting.layer,
        "x": round(planting.x, 3),
        "y": round(planting.y, 3),
        "crown_m": planting.crown_m,
        "source_ref": str(planting.ref),
        "verdict": planting.verdict.value,
        "violations": [_check(c, rulebook) for c in planting.violations],
        "needs_approval": [_check(c, rulebook) for c in planting.approvals],
        "with_root_barrier": [_check(c, rulebook) for c in planting.with_barrier],
        "checks": [_check(c, rulebook) for c in planting.checks],
    }


def _check(check: RuleCheck, rulebook: RuleBook) -> dict[str, Any]:
    return {
        "rule_id": check.rule_id,
        "outcome": check.outcome.value,
        "measured_m": None if check.measured_m is None else round(check.measured_m, 3),
        "threshold_m": check.threshold_m,
        "object_class": check.object_class.value if check.object_class else None,
        "nearest_ref": str(check.nearest) if check.nearest else None,
        "text": describe_check(check, rulebook),
    }


def _rows(planting: AuditedPlanting, rulebook: RuleBook) -> list[dict[str, Any]]:
    """Строка на каждое нарушение, условие барьера или отсутствие данных. У посадки без
    замечаний одна строка без правила, чтобы в таблице были все посадки."""
    base = {
        "number": planting.number,
        "planting_type": planting.planting_type.value,
        "type_basis": planting.type_basis,
        "layer": planting.layer,
        "x": round(planting.x, 3),
        "y": round(planting.y, 3),
        "crown_m": planting.crown_m if planting.crown_m is not None else "",
        "verdict": planting.verdict.value,
    }
    reported = [c for c in planting.checks if c.outcome.value in _REPORTED]
    if not reported:
        return [base]
    rows = []
    for check in reported:
        rule = rulebook.rule(check.rule_id)
        citation = rule.citation if rule else None
        act = rulebook.act_of(citation) if citation else None
        shortfall = ""
        if check.measured_m is not None and check.threshold_m is not None:
            shortfall = round(check.threshold_m - check.measured_m, 3)
        rows.append(
            {
                **base,
                "rule_id": check.rule_id,
                "outcome": check.outcome.value,
                "measured_m": "" if check.measured_m is None else round(check.measured_m, 3),
                "threshold_m": check.threshold_m if check.threshold_m is not None else "",
                "shortfall_m": shortfall,
                "object_class": check.object_class.value if check.object_class else "",
                "nearest_ref": str(check.nearest) if check.nearest else "",
                "act_id": citation.act_id if citation else "",
                "act_title": act.title if act else "",
                "clause": citation.clause if citation else "",
                "quote": citation.quote if citation else "",
                "url": act.url if act else "",
                "text": describe_check(check, rulebook),
            }
        )
    return rows


def _markdown(report: AuditReport) -> str:
    summary = report.summary()
    lines = [
        f"# Нормоконтроль: {report.source_name}",
        "",
        (
            f"Профиль `{report.profile}`, слои посадок `{report.planting_layers}`, "
            f"база правил `{report.rulebook.fingerprint}`."
        ),
        "",
        "| Показатель | Значение |",
        "|---|---|",
        (
            f"| Посадок проверено | {summary['plantings']} "
            f"(деревьев {summary['trees']}, кустарников {summary['shrubs']}) |"
        ),
        (
            f"| Посадок с нарушением отступов | {summary['with_violations']} "
            f"(нарушений {summary['violations']}) |"
        ),
        f"| Допустимы только с прикорневым барьером | {summary['only_with_root_barrier']} |",
        (
            f"| Без нарушений, но требуют согласования (охранная зона ВЛ) | "
            f"{summary['only_needs_approval']} |"
        ),
        (
            f"| Исходные сущности не изменены | {'да' if report.integrity.ok else 'НЕТ'}, "
            f"{report.integrity.unchanged} из {report.integrity.source_entities} |"
        ),
        "",
        "## Нарушения по правилам",
        "",
        "| Правило | Посадок | Основание |",
        "|---|---|---|",
    ]
    for rule_id, count in report.by_rule().items():
        rule = report.rulebook.rule(rule_id)
        clause = ""
        if rule is not None:
            clause = f"{report.rulebook.label_of(rule.citation.act_id)}, {rule.citation.clause}"
        lines.append(f"| `{rule_id}` | {count} | {clause} |")
    worst = sorted(
        (
            (check.threshold_m - check.measured_m, planting, check)
            for planting in report.violating
            for check in planting.violations
            if check.measured_m is not None and check.threshold_m is not None
        ),
        key=lambda item: -item[0],
    )[:_WORST_IN_REPORT]
    if worst:
        lines += ["", f"## {len(worst)} самых больших нарушений", ""]
        lines += [
            f"- Посадка №{planting.number} ({planting.x:.2f}; {planting.y:.2f}), слой "
            f"`{planting.layer}`: {describe_check(check, report.rulebook)}."
            for _, planting, check in worst
        ]
    if report.warnings:
        lines += ["", "## Замечания", ""]
        lines += [f"- {warning}" for warning in report.warnings]
    return "\n".join(lines) + "\n"


def _write_json(path: Path, payload: object) -> Path:
    path.write_bytes(orjson.dumps(payload, option=orjson.OPT_INDENT_2))
    return path


def _write_text(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8", newline="\n")
    return path


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> Path:
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=CSV_COLUMNS, delimiter=";", restval="")
        writer.writeheader()
        writer.writerows(rows)
    return path
