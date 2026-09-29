"""Запись артефактов: plan.json, quality.json, basemap.geojson, scene.json,
interpretations.csv/json, run_manifest.json, verify.json."""

from __future__ import annotations

import csv
import math
import platform
from dataclasses import asdict
from importlib.metadata import PackageNotFoundError, version
from typing import TYPE_CHECKING, Any

import numpy as np
import orjson
import shapely

from green.application.explain import LAWN_LABELS
from green.application.schedule import PIT_SOURCE, SECTIONS, build_schedule
from green.application.surfaces import Material
from green.domain.planting import Placement, Rejection
from green.infrastructure.reports.interpretation_report import (
    write_html,
    write_markdown,
    write_plantings_csv,
)
from green.infrastructure.reports.png import encode_rgba
from green.infrastructure.reports.scene import scene_payload
from green.infrastructure.reports.semantic_review import save_review_geometry

if TYPE_CHECKING:
    from pathlib import Path

    from shapely.geometry.base import BaseGeometry

    from green.application.basemap import Basemap, BasemapFeature
    from green.application.classification import ClassificationReport
    from green.application.results import RunReport
    from green.application.surfaces import SurfaceMap
    from green.domain.effect import StreetEffect
    from green.domain.norms import RuleBook
    from green.domain.objects import Scene
    from green.domain.planting import (
        AssortmentInfo,
        AssortmentSummary,
        Explanation,
        Lawn,
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
    "area_m2",
)
_PACKAGES = ("green", "ezdxf", "shapely", "fastapi", "pydantic")
# Геометрия газона в plan.json: сантиметры - точность чертежа 1:500, больше знаков только
# раздувают файл, который браузер разбирает при открытии прогона.
_LAWN_DIGITS = 2


class FileArtifactSink:
    def save(self, directory: Path, report: RunReport) -> dict[str, Path]:
        directory.mkdir(parents=True, exist_ok=True)
        rows = build_rows(report.plan, report.rulebook)
        return {
            "result.dxf": report.output_dxf,
            "plan.json": _write_json(directory / "plan.json", _plan(report)),
            "interpretations.json": _write_json(directory / "interpretations.json", rows),
            "interpretations.csv": _write_csv(directory / "interpretations.csv", rows),
            "interpretations.md": write_markdown(directory / "interpretations.md", report),
            "report.html": write_html(directory / "report.html", report),
            "plantings.csv": write_plantings_csv(directory / "plantings.csv", report),
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
            # Сцену, как и подоснову, читает браузер, а не человек: без отступов.
            "scene.json": _write_json(
                directory / "scene.json",
                scene_payload(report.plan, report.volumes),
                indent=False,
            ),
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
            "quality.json": _write_json(
                directory / "quality.json",
                quality_payload(report.plan.quality, report.plan.effect),
            ),
            "selection.json": _write_json(
                directory / "selection.json",
                asdict(report.plan.selection) if report.plan.selection is not None else None,
            ),
            "portfolio.json": _write_json(
                directory / "portfolio.json",
                asdict(report.plan.portfolio) if report.plan.portfolio is not None else None,
            ),
            **_surface(directory, report.surface),
            # Исходник сверки комплекта (склеенный чертёж): с ним `green verify` повторяет
            # сверку результата. У одиночного файла исходник - сам входной файл, ссылки нет.
            **({report.merged_dxf.name: report.merged_dxf} if report.merged_dxf else {}),
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
    """Одна строка на пару (решение, правило): эксперт фильтрует по номеру посадки или отказа.

    Текст объяснения - в первой строке решения, а не в каждой строке его проверок: на
    Кустанайской повтор текста около 2 КБ в 24 строках посадки давал 62 из 76 МБ CSV.
    """
    texts = {e.subject_id: e for e in plan.explanations}
    values = plan.quality.values if plan.quality is not None else {}
    rows: list[dict[str, Any]] = []
    for placement in plan.placements:
        own = _rows(placement, placement.checks, texts.get(placement.placement_id), rulebook)
        value = values.get(placement.placement_id)
        if value is not None:
            own = [{**row, "value": value.delta} for row in own]
        rows += _explained_once(own)
    for rejection in plan.rejections:
        rows += _explained_once(
            _rows(rejection, rejection.blocking, texts.get(rejection.rejection_id), rulebook)
        )
    for lawn in plan.lawns:
        rows += _explained_once(_lawn_rows(lawn, texts.get(lawn.lawn_id), rulebook))
    return rows


def _explained_once(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row if i == 0 else {**row, "explanation": ""} for i, row in enumerate(rows)]


def _lawn_rows(
    lawn: Lawn, explanation: Explanation | None, rulebook: RuleBook
) -> list[dict[str, Any]]:
    """Газон: строка на каждое основание участка, площадь - в своей графе."""
    point = lawn.geometry.representative_point()
    base = {
        "kind": "lawn",
        "number": lawn.number,
        "subject_id": lawn.lawn_id,
        "planting_type": lawn.planting_type.value,
        "species_ru": "",
        "species_lat": "",
        "x": round(point.x, 3),
        "y": round(point.y, 3),
        "verdict": "",
        "outcome": lawn.kind.value,
        "reason": f"{LAWN_LABELS[lawn.kind]} газон",
        "explanation": explanation.text if explanation else "",
        "area_m2": round(lawn.area_m2, 2),
    }
    rows = []
    for rule_id in lawn.rule_ids:
        rule = rulebook.rule(rule_id)
        citation = rule.citation if rule else None
        act = rulebook.act_of(citation) if citation else None
        rows.append(
            {
                **base,
                "rule_id": rule_id,
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
        "weak": list(value.weak),
        "flagged": value.flagged,
    }


def quality_payload(
    quality: PlanQuality | None, effect: StreetEffect | None = None
) -> dict[str, Any]:
    """Индекс качества плана: слагаемые с основаниями, штрафы, сводка и лучшие посадки; рядом -
    отдельным блоком - что план даёт улице (effect), с индексом не смешивается."""
    if quality is None:
        return {"index": None, "gate": "индекс не считался", "effect": effect_payload(effect)}
    ranked = sorted(quality.values.values(), key=lambda v: -v.delta)
    return {
        "effect": effect_payload(effect),
        "index": quality.index,
        "gate": quality.gate,
        "summary": list(quality.summary),
        "analysis": list(quality.analysis),
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
            {"id": v.placement_id, "delta": v.delta, "weak": list(v.weak)}
            for v in reversed(ranked)
            if v.delta < 0
        ][:50],
    }


def effect_payload(effect: StreetEffect | None) -> dict[str, Any] | None:
    """Баланс озеленения «было - стало», виды посадок и шумозащита (application/effect)."""
    if effect is None:
        return None
    return {
        "stock_source": effect.stock_source,
        "area_m2": effect.area_m2,
        "curb_m": effect.curb_m,
        "length_m": effect.length_m,
        "measures": [
            {
                "key": m.key,
                "title": m.title,
                "unit": m.unit,
                "before": m.before,
                "after": m.after,
                "delta": m.delta,
                "basis": m.basis,
                "kind": m.kind,
                "note": m.note,
            }
            for m in effect.measures
        ],
        "kinds": [
            {
                "key": k.key,
                "title": k.title,
                "planting_type": k.planting_type,
                "count": k.count,
                "length_m": k.length_m,
                "area_m2": k.area_m2,
                "basis": k.basis,
                "places": dict(k.places),
            }
            for k in effect.kinds
        ],
        "noise": [asdict(b) for b in effect.noise],
        "notes": list(effect.notes),
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
    return {
        **plan_payload(report.plan),
        "run_id": report.run_id,
        "source": _source(report),
        "summary": report.summary(),
        "warnings": list(report.warnings),
        # Журнал склейки - отдельно от предупреждений, которые меняют смысл плана.
        "load_notes": list(report.load_notes),
    }


def plan_payload(plan: Plan) -> dict[str, Any]:
    """Current plan content, without attaching saved-file certificates to a draft."""
    texts = {e.subject_id: e.text for e in plan.explanations}
    values = plan.quality.values if plan.quality is not None else {}
    return {
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
                "place": p.place,
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
                "barrier_m": r.barrier_m,
                "explanation": texts.get(r.rejection_id, ""),
                "blocking": [_check(c) for c in r.blocking],
            }
            for r in plan.rejections
        ],
        "lawns": [
            {
                "id": lawn.lawn_id,
                "number": lawn.number,
                "planting_type": lawn.planting_type.value,
                "kind": lawn.kind.value,
                "area_m2": round(lawn.area_m2, 2),
                "rule_ids": list(lawn.rule_ids),
                "notes": list(lawn.notes),
                "explanation": texts.get(lawn.lawn_id, ""),
                "geometry": _geojson(lawn.geometry),
            }
            for lawn in plan.lawns
        ],
        "warnings": list(plan.warnings),
    }


def _geojson(geometry: BaseGeometry) -> dict[str, Any]:
    """GeoJSON в координатах чертежа: внешний контур против часовой стрелки, отверстия по ней
    (RFC 7946), так правило ненулевого обхода заливки в браузере оставляет ямы пустыми."""
    oriented = shapely.orient_polygons(geometry)
    rounded = shapely.transform(oriented, lambda xy: np.round(xy, _LAWN_DIGITS))
    return orjson.loads(shapely.to_geojson(rounded))


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
        # Подписи материала отдельным списком, а не объектами GeoJSON: они не участвуют в
        # балансе отбора и рисуются текстом, а не геометрией.
        "labels": [
            [round(label.x, 2), round(label.y, 2), label.text, label.material]
            for label in basemap.labels
        ],
        "features": [
            {
                "type": "Feature",
                "properties": _basemap_properties(feature),
                "geometry": orjson.loads(shapely.to_geojson(feature.geometry)),
            }
            for feature in basemap.features
        ],
    }


def _basemap_properties(feature: BasemapFeature) -> dict[str, Any]:
    """Класс объекта и, у хвойного существующего дерева, признак хвойного знака.

    Признак пишется только там, где он есть: у десятков тысяч объектов подосновы лишний
    ключ утяжелил бы выгрузку, которую браузер разбирает при открытии прогона.
    """
    properties: dict[str, Any] = {"class": feature.object_class.value}
    if feature.conifer:
        properties["conifer"] = True
    if feature.vegetation_kind:
        properties["vegetation_kind"] = feature.vegetation_kind
    return properties


# Цвета карты покрытий: грунт - зеленоватый, твёрдое - серый, полупрозрачные, чтобы линии
# подосновы читались поверх. Барьеры и неизвестное - прозрачные.
SURFACE_COLORS = {
    Material.UNKNOWN: (0, 0, 0, 0),
    Material.PAVED: (140, 142, 150, 96),
    Material.SOIL: (104, 158, 104, 88),
    Material.BARRIER: (0, 0, 0, 0),
}
SURFACE_MAX_SIDE = 4096  # пикселей по длинной стороне: больше браузеру не нужно


def _surface(directory: Path, surface: SurfaceMap | None) -> dict[str, Path]:
    """Карта покрытий растром: PNG и привязка к координатам чертежа."""
    if surface is None:
        return {}
    grid = surface.grid
    step = max(1, math.ceil(max(grid.shape) / SURFACE_MAX_SIDE))
    sampled = grid[::step, ::step]
    palette = np.zeros((max(int(m) for m in Material) + 1, 4), dtype=np.uint8)
    for material, color in SURFACE_COLORS.items():
        palette[int(material)] = color
    image = directory / "surface.png"
    image.write_bytes(encode_rgba(palette[sampled]))
    meta = {
        "origin": [surface.origin[0], surface.origin[1]],
        "cell_m": surface.cell * step,
        "width": int(sampled.shape[1]),
        "height": int(sampled.shape[0]),
        "row_order": "строка 0 - минимальный Y чертежа",
        "colors": {m.name.lower(): list(c) for m, c in SURFACE_COLORS.items()},
        "counts": {m.name.lower(): int((grid == m).sum()) for m in Material},
    }
    return {"surface.png": image, "surface.json": _write_json(directory / "surface.json", meta)}


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
