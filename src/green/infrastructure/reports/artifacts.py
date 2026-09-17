"""Запись артефактов: plan.json, interpretations.csv/json, run_manifest.json, verify.json."""

from __future__ import annotations

import csv
import platform
from dataclasses import asdict
from importlib.metadata import PackageNotFoundError, version
from typing import TYPE_CHECKING, Any

import orjson
import shapely

from green.application.schedule import PIT_SOURCE, SECTIONS, build_schedule
from green.domain.planting import Placement, Rejection

if TYPE_CHECKING:
    from pathlib import Path

    from green.application.results import RunReport
    from green.domain.norms import RuleBook
    from green.domain.planting import (
        AssortmentInfo,
        AssortmentSummary,
        Explanation,
        Plan,
        RuleCheck,
        Species,
    )

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
    "reason",
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
            "zones.geojson": _write_json(directory / "zones.geojson", _zones(report.plan)),
            "assortment.json": _write_json(
                directory / "assortment.json",
                _assortment_summary(report.plan.assortment_summary),
            ),
            "planting_schedule.csv": _write_schedule(
                directory / "planting_schedule.csv", report.plan
            ),
            "assortment_shrubs.json": _write_json(
                directory / "assortment_shrubs.json",
                _assortment_summary(report.plan.shrub_assortment_summary),
            ),
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


def _note_row(subject: Rejection, base: dict[str, Any]) -> list[dict[str, Any]]:
    """Отказ не по правилу расстояний (квоты): одна строка с причиной, без акта."""
    if not subject.note:
        return []
    return [{**base, "rule_id": "", "outcome": "composition", "reason": subject.note}]


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
    rows += _species_rows(subject, base, rulebook)
    if isinstance(subject, Rejection):
        rows += _note_row(subject, base)
    return rows


def _species_rows(
    subject: Placement | Rejection, base: dict[str, Any], rulebook: RuleBook
) -> list[dict[str, Any]]:
    """Строки видозависимых норм: 369-ПП, 743-ПП п. 3.6.18, отступ по роду, крона, зона ВЛ."""
    info = subject.assortment if isinstance(subject, Placement) else None
    if info is None:
        return []
    rows = []
    for reason in info.reasons:
        if reason.kind != "norm" or not reason.rule_id:
            continue
        rule = rulebook.rule(reason.rule_id)
        citation = rule.citation if rule else None
        act = rulebook.act_of(citation) if citation else None
        rows.append(
            {
                **base,
                "rule_id": reason.rule_id,
                "outcome": "species",
                "reason": (
                    f"{reason.text}; условие: {reason.condition}"
                    if reason.condition
                    else reason.text
                ),
                "object_class": getattr(getattr(rule, "object_class", None), "value", ""),
                "act_id": citation.act_id if citation else "",
                "act_title": act.title if act else "",
                "clause": citation.clause if citation else "",
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


def _assortment(info: AssortmentInfo | None) -> dict[str, Any] | None:
    if info is None:
        return None
    return {
        "status": info.status,
        "percent": info.percent,
        "factors": {name: round(value, 3) for name, value in info.factors.items()},
        "structure": {"id": info.structure_id, "kind": info.structure_kind},
        "reasons": [
            {
                "kind": r.kind,
                "text": r.text,
                "rule_id": r.rule_id,
                "source": r.source,
                "condition": r.condition,
            }
            for r in info.reasons
        ],
        "alternatives": [
            {"code": a.code, "name_ru": a.name_ru, "percent": a.percent, "why_not": a.why_not}
            for a in info.alternatives
        ],
    }


def _assortment_summary(summary: AssortmentSummary | None) -> dict[str, Any]:
    """Состав плана отдельным файлом: доли, разнообразие, сезонность и что не удалось."""
    if summary is None:
        return {"mode": "none", "counts": {}}
    return {
        "mode": summary.mode,
        "solver": summary.solver,
        "counts": dict(summary.counts),
        "genus_shares": dict(summary.genus_shares),
        "family_shares": dict(summary.family_shares),
        "conifer_share": round(summary.conifer_share, 4),
        "shannon": summary.shannon,
        "decor_by_month": dict(summary.decor_by_month),
        "no_species": summary.no_species,
        "quota_violations": list(summary.quota_violations),
        "existing": dict(summary.existing),
        "rejected_by_kind": dict(summary.rejected_by_kind),
        "rejected_by_rule": dict(summary.rejected_by_rule),
        "notes": list(summary.notes),
    }


def _species(species: Species) -> dict[str, Any]:
    """Краткая карточка вида: остальные поля каталога лежат в config/species.yaml."""
    return {
        "code": species.code,
        "name_ru": species.name_ru,
        "name_lat": species.name_lat,
        "crown_diameter_m": species.crown_diameter_m,
        "life_form": species.life_form.value,
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
                "species": _species(p.species),
                "x": p.x,
                "y": p.y,
                "verdict": p.verdict.value,
                "notes": list(p.notes),
                "explanation": texts.get(p.placement_id, ""),
                "assortment": _assortment(p.assortment),
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
                "note": r.note,
                "explanation": texts.get(r.rejection_id, ""),
                "blocking": [_check(c) for c in r.blocking],
            }
            for r in plan.rejections
        ],
        "warnings": list(report.warnings),
    }


def _zones(plan: Plan) -> dict[str, Any]:
    """Зоны допустимости в GeoJSON в координатах чертежа (метры, без геопривязки)."""
    return {
        "type": "FeatureCollection",
        "crs_note": "координаты чертежа в метрах, не WGS84",
        "features": [
            {
                "type": "Feature",
                "properties": {"verdict": zone.verdict.value, "area_m2": round(zone.area_m2)},
                "geometry": orjson.loads(shapely.to_geojson(zone.geometry)),
            }
            for zone in plan.zones
        ],
    }


def _manifest(report: RunReport) -> dict[str, Any]:
    rulebook = report.rulebook
    rules = rulebook.all_rules
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
        "unexportable": integrity.unexportable,
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


SCHEDULE_COLUMNS = (
    "№ п/п",
    "Наименование",
    "Латинское название",
    "Кол-во, шт.",
    "Стандарт",
    "Размер кома, м",
    "Посадочная яма, м",
    "Площадь под посадочные ямы, м2",
    "Условия посадки",
)


def _area(value: float) -> str:
    """Площадь с десятичной запятой: ведомость открывают в Excel с русской локалью."""
    return f"{value:.2f}".replace(".", ",")


def _write_schedule(path: Path, plan: Plan) -> Path:
    """Ведомость посадочного материала в графах ведомости проектировщика, с итогами."""
    rows = build_schedule(plan.placements)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream, delimiter=";")
        writer.writerow(SCHEDULE_COLUMNS)
        for section in SECTIONS:
            members = [row for row in rows if row.section == section]
            if not members:
                continue
            writer.writerow(["", section])
            for row in members:
                writer.writerow(
                    [
                        row.number,
                        row.name_ru,
                        row.name_lat,
                        row.count,
                        row.stock.group,
                        row.stock.ball,
                        row.stock.pit,
                        _area(row.pit_area_m2),
                        "; ".join(row.conditions),
                    ]
                )
            total_area = sum(r.pit_area_m2 for r in members)
            writer.writerow(
                ["", "Всего:", "", sum(r.count for r in members), "", "", "", _area(total_area)]
            )
        trees = [r for r in rows if "деревья" in r.section]
        shrubs = [r for r in rows if "кустарники" in r.section]
        for label, members in (("Всего деревьев", trees), ("Всего кустарников", shrubs)):
            area = sum(r.pit_area_m2 for r in members)
            writer.writerow(["", label, "", sum(r.count for r in members), "", "", "", _area(area)])
        writer.writerow(["", f"Размеры ям: {PIT_SOURCE}; стандарт саженца - параметр проекта"])
    return path


def _version(name: str) -> str | None:
    try:
        return version(name)
    except PackageNotFoundError:
        return None
