"""Запись артефактов: plan.json, quality.json, basemap.geojson, interpretations.csv/json,
run_manifest.json, verify.json."""

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
from green.infrastructure.reports.semantic_review import save_review_geometry

if TYPE_CHECKING:
    from pathlib import Path

    from green.application.basemap import Basemap
    from green.application.classification import ClassificationReport
    from green.application.results import RunReport
    from green.domain.norms import RuleBook
    from green.domain.objects import Scene
    from green.domain.planting import (
        AssortmentInfo,
        AssortmentSummary,
        Explanation,
        Plan,
        RuleCheck,
        Species,
    )
    from green.domain.quality import PlanQuality, PlantingValue

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
    "value",
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
            "export_validation.json": _write_json(
                directory / "export_validation.json",
                {"ok": report.export_validation.ok, **asdict(report.export_validation)}
                if report.export_validation
                else None,
            ),
            "validation.json": _write_json(
                directory / "validation.json",
                {"ok": report.validation.ok, **asdict(report.validation)}
                if report.validation
                else None,
            ),
            "layers_report.json": _write_json(directory / "layers_report.json", _layers(report)),
            "classification.json": _write_json(
                directory / "classification.json", classification_payload(report.classification)
            ),
            "input_read.json": _write_json(
                directory / "input_read.json", asdict(report.read_diagnostics)
            ),
            "assembly.json": _write_json(
                directory / "assembly.json", asdict(report.assembly) if report.assembly else None
            ),
            "zones.geojson": _write_json(directory / "zones.geojson", _zones(report.plan)),
            "basemap.geojson": self.save_basemap(directory, report.basemap),
            "rules.json": _write_json(directory / "rules.json", _rules(report.rulebook)),
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
            "quality.json": _write_json(directory / "quality.json", _quality(report.plan.quality)),
            "selection.json": _write_json(
                directory / "selection.json",
                asdict(report.plan.selection) if report.plan.selection is not None else None,
            ),
            "portfolio.json": _write_json(
                directory / "portfolio.json",
                asdict(report.plan.portfolio) if report.plan.portfolio is not None else None,
            ),
        }

    def save_basemap(self, directory: Path, basemap: Basemap | None) -> Path:
        """Подоснова отдельно от остального: карта забирает её, пока план ещё считается.

        Единственный артефакт, который пишется без отступов: его читает не человек, а
        браузер, и на Камчатской отступы раздували файл с 4 МБ до 18 МБ - четверть секунды
        разбора на ровном месте.
        """
        directory.mkdir(parents=True, exist_ok=True)
        return _write_json(directory / "basemap.geojson", _basemap(basemap), indent=False)

    def save_classification(
        self,
        directory: Path,
        report: ClassificationReport,
        *,
        scene: Scene | None = None,
        source: Path | None = None,
    ) -> dict[str, Path]:
        directory.mkdir(parents=True, exist_ok=True)
        saved = {
            "classification.json": _write_json(
                directory / "classification.json", classification_payload(report)
            )
        }
        if scene is not None:
            saved.update(save_review_geometry(directory, report, scene, source))
        return saved


def classification_payload(report: ClassificationReport | None) -> dict[str, Any] | None:
    return {"ready": report.ready, **asdict(report)} if report is not None else None


def build_rows(plan: Plan, rulebook: RuleBook) -> list[dict[str, Any]]:
    """Одна строка на пару (решение, правило): эксперт фильтрует по номеру посадки или отказа."""
    texts = {e.subject_id: e for e in plan.explanations}
    values = plan.quality.values if plan.quality is not None else {}
    rows: list[dict[str, Any]] = []
    for placement in plan.placements:
        own = _rows(placement, placement.checks, texts.get(placement.placement_id), rulebook)
        value = values.get(placement.placement_id)
        if value is not None:
            own = [{**row, "value": value.delta} for row in own]
        rows += own
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


def _value(value: PlantingValue | None) -> dict[str, Any] | None:
    if value is None:
        return None
    return {
        "delta": value.delta,
        "percentile": value.percentile,
        "by_term": dict(value.by_term),
        "reasons": list(value.reasons),
        "scope": value.scope,
    }


def _quality(quality: PlanQuality | None) -> dict[str, Any]:
    """Индекс качества плана: слагаемые с основаниями, штрафы, сводка и лучшие посадки."""
    if quality is None:
        return {"index": None, "gate": "индекс не считался"}
    ranked = sorted(quality.values.values(), key=lambda v: -v.delta)
    return {
        "index": quality.index,
        "gate": quality.gate,
        "summary": list(quality.summary),
        "terms": [
            {
                "key": t.key,
                "title": t.title,
                "weight": t.weight,
                "score": t.score,
                "basis": t.basis,
                "note": t.note,
                "measure": dict(t.measure),
            }
            for t in quality.terms
        ],
        "penalty": quality.penalty,
        "penalties": dict(quality.penalties),
        "top": [
            {"id": v.placement_id, "delta": v.delta, "reasons": list(v.reasons)}
            for v in ranked[:10]
        ],
        "negative": [
            {"id": v.placement_id, "delta": v.delta, "reasons": list(v.reasons)}
            for v in reversed(ranked)
            if v.delta < 0
        ][:50],
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
    values = plan.quality.values if plan.quality is not None else {}
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
                "value": _value(values.get(p.placement_id)),
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


def _rules(rulebook: RuleBook) -> dict[str, Any]:
    """Свод норм прогона: rule_id -> акт, пункт, цитата.

    Отдельный маленький артефакт нужен потому, что `interpretations.json` на настоящем
    чертеже весит десятки мегабайт: карта в браузере соединяет `rule_id` из plan.json с
    пунктом отсюда, а не тащит все строки объяснений.
    """
    items = {}
    for rule in rulebook.all_rules:
        citation = rule.citation
        act = rulebook.act_of(citation)
        items[rule.rule_id] = {
            "rule_id": rule.rule_id,
            "object_class": getattr(getattr(rule, "object_class", None), "value", ""),
            "min_distance_m": getattr(rule, "min_distance_m", None),
            "measure_to": getattr(getattr(rule, "measure_to", None), "value", ""),
            "severity": getattr(getattr(rule, "severity", None), "value", ""),
            "act_id": citation.act_id,
            "act_title": act.title if act else "",
            "act_short": act.short if act else "",
            "act_edition": act.edition if act else "",
            "url": act.url if act else "",
            "clause": citation.clause,
            "quote": citation.quote,
            "status": citation.status.value,
            "related": [
                f"{rulebook.label_of(ref.act_id)}, {ref.clause}" for ref in citation.related
            ],
        }
    return {"fingerprint": rulebook.fingerprint, "total": len(items), "rules": items}


def _basemap(basemap: Basemap | None) -> dict[str, Any]:
    """Подоснова для карты в вебе, GeoJSON в координатах чертежа.

    counts едет рядом с features намеренно: по трём числам видно, что отбор не потерял объект
    молча. features_out + сумма dropped обязана равняться features_in.
    """
    if basemap is None:
        return {
            "type": "FeatureCollection",
            "crs_note": "координаты чертежа в метрах, не WGS84",
            "counts": {"features_in": 0, "features_out": 0, "dropped": {}},
            "bbox": [0.0, 0.0, 0.0, 0.0],
            "features": [],
        }
    return {
        "type": "FeatureCollection",
        "crs_note": "координаты чертежа в метрах, не WGS84",
        "counts": {
            "features_in": basemap.features_in,
            "features_out": basemap.features_out,
            "dropped": dict(basemap.dropped),
            # С какой детализацией собрана карта: на тяжёлом чертеже она огрубляется, и
            # читатель выгрузки должен видеть, насколько, а не гадать по картинке.
            "tolerance_m": basemap.tolerance_m,
            "min_span_m": basemap.min_span_m,
        },
        "bbox": list(basemap.bbox),
        "features": [
            {
                "type": "Feature",
                "properties": {"class": feature.object_class.value},
                "geometry": orjson.loads(shapely.to_geojson(feature.geometry)),
            }
            for feature in basemap.features
        ],
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


def _write_json(path: Path, payload: object, *, indent: bool = True) -> Path:
    option = orjson.OPT_NON_STR_KEYS | (orjson.OPT_INDENT_2 if indent else 0)
    path.write_bytes(orjson.dumps(payload, option=option))
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
