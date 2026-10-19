"""Запись артефактов: plan.json, quality.json, basemap.geojson, scene.json,
interpretations.csv/json, run_manifest.json, verify.json."""

from __future__ import annotations

import csv
import math
import platform
import re
from dataclasses import asdict
from importlib.metadata import PackageNotFoundError, version
from typing import TYPE_CHECKING, Any

import ezdxf
import numpy as np
import orjson
import shapely
from openpyxl import Workbook

from green.application.classification import recognition_summary
from green.application.explain import LAWN_LABELS
from green.application.name_model import name_key
from green.application.schedule import PIT_SOURCE, SECTIONS, build_schedule
from green.application.surfaces import Material, cells_area
from green.domain.norms import LawnKind
from green.domain.objects import ObjectClass
from green.domain.planting import Placement, Rejection
from green.infrastructure.cad.writer import RESULT_LAYERS_SUFFIX, save_result_layers
from green.infrastructure.reports.interpretation_report import (
    write_html,
    write_markdown,
    write_plantings_csv,
)
from green.infrastructure.reports.note_docx import write_note
from green.infrastructure.reports.png import encode_rgba
from green.infrastructure.reports.scene import scene_payload
from green.infrastructure.reports.semantic_review import save_review_geometry

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from shapely.geometry.base import BaseGeometry

    from green.application.basemap import Basemap, BasemapFeature
    from green.application.classification import ClassificationReport
    from green.application.name_hints import NameHint
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
            "workbook.xlsx": write_workbook(
                directory / "workbook.xlsx", report.plan, report.rulebook
            ),
            "note.docx": write_note(directory / "note.docx", report),
            "result_layers.dxf": write_result_layers(
                report.output_dxf, directory / "result_layers.dxf"
            ),
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
                directory / "classification.json",
                classification_payload(report.classification, report.name_hints),
            ),
            "input_read.json": _write_json(
                directory / "input_read.json", asdict(report.read_diagnostics)
            ),
            # Подсказки LLM по именам слоёв: только когда их спрашивали и было что сказать.
            **(
                {
                    "name_hints.json": _write_json(
                        directory / "name_hints.json",
                        {
                            "note": (
                                "Предположения LLM о классе слоёв, которые сервис понял только "
                                "по геометрии. План от них не зависит; принять подсказку - "
                                "назначить класс слою (layer_classes) и перезапустить."
                            ),
                            "hints": [asdict(h) for h in report.name_hints],
                        },
                    )
                }
                if report.name_hints
                else {}
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
            **_surface(directory, report.display_surface or report.surface, report.basemap),
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
            # Final classification may later include GIS and contextual refinements.
            # Review assignments must refer to this exact CAD-only interpretation.
            saved["review-classification.json"] = _write_json(
                directory / "review-classification.json", classification_payload(report)
            )
            saved.update(save_review_geometry(directory, report, scene, source))
        return saved


def classification_payload(
    report: ClassificationReport | None, hints: Sequence[NameHint] = ()
) -> dict[str, Any] | None:
    """classification.json; подсказка LLM по имени (application/name_hints.py) кладётся в каждую
    группу этого имени полем llm_hint - её показывает таблица страницы уточнения."""
    if report is None:
        return None
    body = asdict(report)
    groups: list[dict[str, Any]] = body["groups"]
    by_name = {h.name: h for h in hints}
    for group in groups:
        hint = by_name.get(name_key(group["layer"], group["block"]))
        if hint is not None:
            group["llm_hint"] = {
                "suggestion": hint.suggestion,
                "confidence": hint.confidence,
                "model": hint.model,
            }
    return {"ready": report.ready, "recognition": recognition_summary(report), **body}


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
        "reason": LAWN_LABELS[lawn.kind]
        if lawn.kind is LawnKind.FLOWERBED
        else f"{LAWN_LABELS[lawn.kind]} газон",
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


_DECOR_SEASON = "слагаемое индекса «Сезонность» считает деревья и кустарники вместе"
# Подпись decor_by_month: чьи это месяцы. Без неё пустой июль в сводке деревьев спорит с
# сезонностью индекса, где июль закрыл кустарник.
DECOR_NOTES = {
    "tree": (
        "Месяцы декоративности деревьев плана: сколько деревьев декоративны в каждом месяце "
        f"(по каталогу видов). Кустарники здесь не считаются; {_DECOR_SEASON}."
    ),
    "shrub": (
        "Месяцы декоративности кустарников плана: сколько кустарников декоративны в каждом "
        f"месяце (по каталогу видов). Деревья здесь не считаются; {_DECOR_SEASON}."
    ),
    "mixed": (
        "Месяцы декоративности деревьев и кустарников плана: сколько посадок декоративны в "
        "каждом месяце (по каталогу видов), как их считает слагаемое индекса «Сезонность»."
    ),
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
        "decor_by_month_of": summary.decor_of,
        "decor_by_month_note": DECOR_NOTES.get(summary.decor_of, ""),
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
                "mix": lawn.mix,
                "plants": [
                    {"name_ru": name, "name_lat": latin, "count": count}
                    for name, latin, count in lawn.plants
                ],
                "explanation": texts.get(lawn.lawn_id, ""),
                "geometry": _geojson(lawn.geometry),
            }
            for lawn in plan.lawns
        ],
        "warnings": list(plan.warnings),
        "edits": [
            {
                "kind": m.kind,
                "placement_id": m.placement_id,
                "x": m.x,
                "y": m.y,
                "from_x": m.from_x,
                "from_y": m.from_y,
                "species_ru": m.species_ru,
            }
            for m in plan.edits
        ],
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
        "source_conflicts": basemap.source_conflicts.payload()
        if basemap.source_conflicts
        else None,
        # Подписи материала отдельным списком, а не объектами GeoJSON: они не участвуют в
        # балансе отбора и рисуются текстом, а не геометрией.
        "labels": [
            [round(label.x, 2), round(label.y, 2), label.text, label.material]
            for label in basemap.labels
        ],
        # Оси оград для 3D: двойная линия знака, штрихи и углы - одной линией (fences.py).
        "fence_axes": [
            [[round(x, 2), round(y, 2)] for x, y in axis.coords] for axis in basemap.fence_axes
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
    if feature.dashed:
        properties["dashed"] = True
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
# Контуры грунта и покрытия для 3D: точные упрощаются до 5 см, выведенные растром - до полутора
# клеток (лесенка клеток становится прямой). Щели по линиям бортов остаются: по ним 3D-вид
# отличает тротуар от проезжей части (surfaceMask.ts) и потом сам их закрывает.
SURFACE_AREA_TOLERANCE_M = 0.05
SURFACE_RASTER_TOLERANCE_CELLS = 1.5
# Повороты скругляются (пользователь, 17.10.2026: «где поворот - закругление»): излом в этих
# пределах срезается, прямой угол остаётся.
SURFACE_ROUND_TURN_DEG = (5.0, 60.0)
SURFACE_ROUND_PASSES = 2
# Поворот, а не пила: оба звена излома не короче этого, м.
ROUND_MIN_SEG_M = 1.5
# Наибольший срез угла при скруглении, м.
ROUND_CUT_M = 1.0
# Части покрытия для 3D: проезжая часть опускается на высоту борта, тротуар и плитка - нет.
PAVED_ROAD, PAVED_ASPHALT, PAVED_PAVERS, PAVED_UNKNOWN = "road", "asphalt", "pavers", "paved"
# Специальное покрытие площадок (резиновая крошка): «СПЕЦ.ПОКР.», «ДЕТ.ПЛ.» Мосгеотреста.
PAVED_SPECIAL = "special"
# Полоса покрытия от этой ширины без плитки - проезд: тротуары дворов 1,5-3 м, проезды от 3,5 м.
ROAD_MIN_WIDTH_M = 3.5
# Дорожка уже 2 x SPECIAL_PATH_M, вошедшая в площадку, - не резина, м.
SPECIAL_PATH_M = 1.5
# Тело площадки, отделённое от сети, - не больше этой доли части; больше - решают голоса.
SPECIAL_BODY_SHARE = 0.8
# Сетка проезжей части шире её контура: край маски на 3D не точнее пикселя, дыра в земле
# у борта должна попадать на асфальт, а не в пустоту.
ROAD_MESH_MARGIN_M = 0.5
SURFACE_MIN_PART_M2 = 0.5
# Допуск снятия пилы и щепок с края газона, м: меньше ширины узкой полосы газона у борта.
SOIL_TIDY_M = 0.25
# Газон-остров среди покрытия (клумба, газон в кольце дорожек) - для показа грунт.
ISLAND_MAX_M2 = 400.0
ISLAND_RING_M = 1.0
ISLAND_PAVED_SHARE = 0.6
FLOWERBED_LABEL_M = 8.0
ISLAND_GRID_M = 1e-3
# Остров режет контур покрытия чертежа, только если лежит в нём хотя бы на эту долю.
ISLAND_INSIDE_DRAWN_SHARE = 0.5
# Покрытие улицы для пересечений режется на куски не больше стольких вершин (_subdivided).
SUBDIVIDE_VERTICES = 256
SUBDIVIDE_MIN_M = 0.01
# Клумба - малый остров: большой газон в кольце дорожек цветником не становится.
FLOWERBED_MAX_M2 = 120.0
FLOWERBED_PHRASE = re.compile(r"КЛУМБ|ЦВЕТН")
# Грань линий чертежа отдаётся материалу растра, если его в грани не меньше этой доли.
FACE_MAJORITY = 0.5
FACE_MIN_M2 = 0.5
_FACE_LINE_TYPES = frozenset({"LineString", "MultiLineString", "LinearRing"})
PAVED_SMOOTH_M = 0.5
# Щепки сглаженного растра за краем контура чертежа уже 2 x DRAWN_SLIVER_M снимаются: это
# хорды упрощения у вогнутых скруглений, а не покрытие.
DRAWN_SLIVER_M = 0.3
DRAWN_SEAM_M = 0.02
DRAWN_JOG_M = 0.15
DRAWN_HOLE_M2 = 1.0
DRAWN_SIMPLIFY_M = 0.04
# Звено кольца в surface.json не короче этого, м.
RING_MIN_SEG_M = 0.05
RING_MIN_POINTS = 4
# Подписи материала съёмки Мосгеотреста: «А» - асфальт, «Ц» - цементобетон, «ПЛ» - плитка,
# «Б», «БР» - брусчатка.
ASPHALT_LABELS = frozenset({"А", "АСФ", "Ц"})
PAVERS_LABELS = frozenset({"ПЛ", "ПЛИТКА", "Б", "БР"})
PAVERS_PHRASE = re.compile(r"ПЛИТК|БРУСЧ")
SPECIAL_PHRASE = re.compile(r"^СПЕЦ|^ДЕТ\.?\s*ПЛ")


def _surface(
    directory: Path, surface: SurfaceMap | None, basemap: Basemap | None = None
) -> dict[str, Path]:
    """Карта покрытий растром: PNG и привязка к координатам чертежа."""
    if surface is None:
        return {}
    # Растр для показа: грань между линиями чертежа одним материалом (surfaces.display_grid).
    grid = surface.grid if surface.display_grid is None else surface.display_grid
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
        "areas": _surface_areas(surface, sampled, surface.cell * step, basemap),
    }
    if surface.stage_report is not None:
        meta["stage_resolution"] = asdict(surface.stage_report)
    return {"surface.png": image, "surface.json": _write_json(directory / "surface.json", meta)}


def _surface_areas(
    surface: SurfaceMap, grid: np.ndarray, cell: float, basemap: Basemap | None = None
) -> dict[str, Any]:
    """Контуры грунта и покрытия для 3D-вида: растр - клетки 0,5-1 м, его край на 3D выходил
    лесенкой с выгрызами (пользователь, 17.10.2026). Где материал задан контуром (полигон
    чертежа, замкнутая грань), берётся контур; где только растром (разлив от подписей,
    запасной грунт) - растр в контурах, выпрямленный с допуском в полторы клетки. Полигон -
    список колец: внешнее, затем дыры."""
    uncertain = surface.uncertainty_area
    # Для показа покрытие, заданное контуром чертежа, не отдаётся растру ни в полосе
    # погрешности линии, ни в спорной грани: растр там выпрямлялся и давал на краю площадки
    # срезанные углы и зацепы, по которым ломался борт (Харьковская, 19.10.2026). Проверка
    # посадок читает неопределённость по-прежнему.
    exact_paved = surface.paved_area
    exact_soil = _without(surface.soil_area, shapely.union_all([exact_paved, uncertain]))
    tolerance = cell * SURFACE_RASTER_TOLERANCE_CELLS
    raster_paved = cells_area(grid == int(Material.PAVED), surface.origin, cell)
    raster_soil = cells_area(grid == int(Material.SOIL), surface.origin, cell)
    # Растр разлива - капли с круглым краем, перелезающие через ограду и борт. Край
    # материала берётся по линиям чертежа: грань, замкнутая оградой, бортом, краем покрытия
    # и стеной, целиком того материала, которого в ней больше (пользователь, 18.10.2026:
    # «плитка до забора, как у площадки»).
    raster_paved, raster_soil = _snap_to_faces(raster_paved, raster_soil, basemap)
    paved = shapely.union_all(
        [
            _without(
                _off_drawn_slivers(_simplified(raster_paved, tolerance), raster_paved, exact_paved),
                exact_soil,
            ),
            exact_paved,
        ]
    )
    soil = _tidy(
        _without(
            shapely.union_all([_simplified(raster_soil, tolerance), exact_soil]),
            shapely.union_all([paved, uncertain]),
        )
    )
    islands, flowerbeds = _lawn_islands(basemap, paved)
    drawn_beds = _drawn_beds(basemap)
    if drawn_beds is not None:
        flowerbeds = shapely.union_all([g for g in (flowerbeds, drawn_beds) if g is not None])
        islands = shapely.union_all([g for g in (islands, drawn_beds) if g is not None])
    islands = _islands_off_drawn(islands, exact_paved)
    if islands is not None:
        paved = _without(paved, islands)
        soil = shapely.union_all([soil, islands]) if soil is not None else islands
    parts, kinds = _paved_parts(paved, basemap, exact_paved)
    parts, kinds = _walk_ends_to_road(parts, kinds)
    parts, kinds = _exploded(_walk_notches_paved(parts, kinds, soil, basemap), kinds)
    parts = [_without_artifact_holes(part, soil) for part in parts]
    roads = [part for part, kind in zip(parts, kinds, strict=True) if kind == PAVED_ROAD]
    mesh = (
        shapely.union_all(roads).buffer(ROAD_MESH_MARGIN_M, join_style="mitre") if roads else None
    )
    exported = _export_parts(parts, kinds)
    return {
        "soil": _rings(soil),
        "paved": exported[0],
        "paved_kind": exported[1],
        "road_mesh": _rings(mesh),
        "flowerbeds": _rings(flowerbeds),
    }


# Выемка тротуара уже 2 x WALK_NOTCH_M, где нет ни газона, ни дома, ни другого покрытия, -
# крыльцо, вход или отмостка: она мостится тем же покрытием, м.
WALK_NOTCH_M = 1.5
WALK_NOTCH_MIN_M2 = 0.3


def _walk_notches_paved(
    parts: list[BaseGeometry],
    kinds: list[str],
    soil: BaseGeometry | None,
    basemap: Basemap | None,
) -> list[BaseGeometry]:
    """Узкие выемки тротуара без материала отходят тротуару.

    У входа в дом съёмка рисует крыльцо линиями, без подписи материала: выемка между
    дорожкой и стеной оставалась «неизвестной», в 3D неизвестное - газон, и у крыльца стоял
    круглый островок травы с асфальтовыми углами (Харьковская, 19.10.2026)."""
    houses = _class_area(basemap.features, ObjectClass.BUILDING) if basemap is not None else None
    blocked = shapely.union_all([g for g in (soil, houses) if g is not None])
    tree = shapely.STRtree(parts) if parts else None
    out = list(parts)
    r = WALK_NOTCH_M
    for i, kind in enumerate(kinds):
        if kind not in {PAVED_ASPHALT, PAVED_PAVERS} or tree is None:
            continue
        part = out[i]
        # Замыкание с прямыми углами: прямоугольная выемка заливается, а внутренний угол
        # дорожки у стены дома не получает скругления.
        notch = _areal(
            _areal(part.buffer(r, join_style="mitre").buffer(-r, join_style="mitre")).difference(
                part
            )
        )
        # Разность бывает вырожденной (линия по краю части): у неё нет рамки для обрезки.
        if notch.is_empty or notch.area < WALK_NOTCH_MIN_M2:
            continue
        # Вычитаются только соседи и газон с домами в рамке выемки: целиком это долго.
        box = notch.bounds
        neighbours = [out[int(k)] for k in tree.query(notch) if int(k) != i]
        cut = shapely.union_all(
            [
                *[shapely.clip_by_rect(g, *box) for g in neighbours],
                shapely.clip_by_rect(blocked, *box),
            ]
        )
        notch = _areal(notch.difference(cut))
        pieces = [g for g in shapely.get_parts(notch) if g.area >= WALK_NOTCH_MIN_M2]
        if pieces:
            out[i] = _areal(shapely.union_all([part, *pieces]))
    return out


# Дыра в покрытии меньше этого и не газон - след знака колодца или обрезка дорожки, м².
ARTIFACT_HOLE_M2 = 4.0


def _without_artifact_holes(part: BaseGeometry, soil: BaseGeometry | None) -> BaseGeometry:
    """Малые дыры покрытия, под которыми нет газона, заливаются: в 3D борт обходил их
    островком посреди проезда (Кустанайская, 19.10.2026). Газон-остров и клумба остаются."""
    if part.geom_type != "Polygon" or not part.interiors:
        return part
    holes = []
    for ring in part.interiors:
        hole = shapely.Polygon(ring)
        lawn = soil is not None and _intersection_area(hole, soil) >= hole.area / 2
        if hole.area >= ARTIFACT_HOLE_M2 or lawn:
            holes.append(ring)
    return shapely.Polygon(part.exterior, holes)


# Конец дорожки в выемке проезда меньше этой доли дорожки и не меньше WALK_END_MIN_M2 -
# конец, заехавший на проезд; меньшее - скругление угла, его не трогаем.
WALK_END_SHARE = 0.5
WALK_END_MIN_M2 = 1.0
# Выемка проезда уже этого замыкается, м: проход дорожки в борту - 1,5-3 м.
WALK_END_MOUTH_M = 3.0
# Дорожка ближе этого к проезду - примыкает к нему, м.
WALK_END_TOUCH_M = 0.3


def _walk_ends_to_road(
    parts: list[BaseGeometry], kinds: list[str]
) -> tuple[list[BaseGeometry], list[str]]:
    """Конец тротуара или дорожки, заехавший в выемку проезда, - проезд.

    Дорожка съёмки часто нарисована дальше борта, на сам проезд: в 3D её конец стоял
    островом в опущенном проезде, и борт обходил его прямоугольником посреди асфальта
    (Кустанайская, 19.10.2026). Выемка проезда уже WALK_END_MOUTH_M замыкается, и то, что
    дорожка занимает внутри замкнутого проезда, отходит проезду."""
    road_ids = [i for i, kind in enumerate(kinds) if kind == PAVED_ROAD]
    if not road_ids:
        return parts, kinds
    road_tree = shapely.STRtree([parts[i] for i in road_ids])
    closed: dict[int, BaseGeometry] = {}
    out = list(parts)
    r = WALK_END_MOUTH_M / 2
    for i, kind in enumerate(kinds):
        if kind not in {PAVED_ASPHALT, PAVED_PAVERS}:
            continue
        for k in road_tree.query(out[i], predicate="dwithin", distance=WALK_END_TOUCH_M):
            road = road_ids[int(k)]
            if road not in closed:
                closed[road] = _areal(out[road].buffer(r).buffer(-r))
            end = _areal(out[i].intersection(closed[road]))
            if end.is_empty or not WALK_END_MIN_M2 <= end.area < WALK_END_SHARE * out[i].area:
                continue
            # Между дорожкой и проездом бывает щель в доли метра: склейка с замыканием, иначе
            # конец остаётся островом проезда со своим бортом.
            g = WALK_END_TOUCH_M
            out[road] = _areal(shapely.union_all([out[road], end]).buffer(g).buffer(-g))
            out[i] = _areal(out[i].difference(out[road]))
    return _exploded(out, kinds)


def _exploded(
    parts: Sequence[BaseGeometry], kinds: Sequence[str]
) -> tuple[list[BaseGeometry], list[str]]:
    """Часть из нескольких многоугольников - несколько частей того же вида.

    Обработка части (разрез концом дорожки, выемка у крыльца, объединение) может оставить
    мультиполигон, а выгрузка и 3D ждут у каждой части одно внешнее кольцо: чертёж жюри
    (паспорт ОГХ 236287.dxf) на этом падал (19.10.2026)."""
    flat = [
        (piece, kind)
        for part, kind in zip(parts, kinds, strict=True)
        for piece in shapely.get_parts(part)
        if piece.geom_type == "Polygon" and not piece.is_empty
    ]
    return [piece for piece, _ in flat], [kind for _, kind in flat]


def _lawn_islands(
    basemap: Basemap | None, paved: BaseGeometry | None
) -> tuple[BaseGeometry | None, BaseGeometry | None]:
    """Газоны-острова среди покрытия и цветники среди них - для показа.

    Полигон газона чертежа не больше ISLAND_MAX_M2, у которого полоса ISLAND_RING_M снаружи
    хотя бы на ISLAND_PAVED_SHARE - покрытие, - остров: клумба посреди площади, газон в
    кольце дорожек. Карта покрытий могла снять его подписью покрытия внутри (подпись
    вазы или постамента «Ц» в клумбе у дома 1А на Харьковской, пользователь 19.10.2026:
    «стёр клумбу»), и 3D рисовал на его месте плитку. Подпись «КЛУМБА» или «ЦВЕТНИК» ближе
    FLOWERBED_LABEL_M - цветник. Проверку посадок это не меняет."""
    if basemap is None or paved is None or paved.is_empty:
        return None, None
    lawns, rings = [], []
    for f in basemap.features:
        if f.object_class is not ObjectClass.LAWN or f.geometry.geom_type not in {
            "Polygon",
            "MultiPolygon",
        }:
            continue
        for lawn in shapely.get_parts(f.geometry):
            if not 0 < lawn.area <= ISLAND_MAX_M2:
                continue
            ring = lawn.buffer(ISLAND_RING_M).difference(lawn)
            if ring.area:
                lawns.append(lawn)
                rings.append(ring)
    covered = _overlap_areas(rings, paved)
    islands = [
        lawn
        for lawn, ring, area in zip(lawns, rings, covered, strict=True)
        if area >= ISLAND_PAVED_SHARE * ring.area
    ]
    if not islands:
        return None, None
    names = [lb for lb in basemap.labels if FLOWERBED_PHRASE.search(lb.text.strip().upper())]
    # Подпись съёмки стоит у выноски, в нескольких метрах: цветник - ближайший к ней остров.
    small = [lawn for lawn in islands if lawn.area <= FLOWERBED_MAX_M2]
    beds = []
    for lb in names if small else ():
        point = shapely.Point(lb.x, lb.y)
        nearest = min(small, key=point.distance)
        if point.distance(nearest) <= FLOWERBED_LABEL_M and nearest not in beds:
            beds.append(nearest)
    return shapely.union_all(islands), (shapely.union_all(beds) if beds else None)


# Классы, чьим замкнутым контуром съёмка обводит клумбу: пунктирный круг «Топографических
# объектов» с подписью «КЛУМБА» внутри (Харьковская, Кустанайская), край площадки, садовый
# борт, газон. Здания, проезды и оформление клумбой не бывают.
_BED_CLASSES = frozenset(
    {
        ObjectClass.OBSTACLE,
        ObjectClass.CONTOUR,
        ObjectClass.PAVEMENT_EDGE,
        ObjectClass.CURB,
        ObjectClass.LAWN,
        ObjectClass.UNKNOWN,
    }
)
# Подпись у края контура клумбы (точка вставки текста - его левый нижний угол), м.
BED_LABEL_REACH_M = 0.5
BED_MIN_M2 = 1.0
# Круглая клумба без подписи: круглость 4пS/P² не меньше этого, площадь не больше, м².
ROUND_BED_MIN = 0.85
ROUND_BED_MAX_M2 = 60.0
# Недозамкнутый контур клумбы замыкается, если концы ближе этого, м.
BED_CLOSE_M = 0.5
# Углы клумбы скругляются этим радиусом, пока она не теряет больше 1 - BED_ROUND_KEEP площади.
BED_ROUND_M = 0.6
BED_ROUND_KEEP = 0.85


def _drawn_beds(basemap: Basemap | None) -> BaseGeometry | None:
    """Клумбы, обведённые замкнутым контуром с подписью «КЛУМБА» или «ЦВЕТНИК» внутри.

    Съёмка рисует клумбу пунктирным кругом, и пока ридер не сшивал штрихи, контура не было, а
    клумба посреди газона или тротуара в 3D пропадала. Для каждой подписи берётся наименьший
    замкнутый контур вокруг неё не больше FLOWERBED_MAX_M2."""
    if basemap is None:
        return None
    names = [
        shapely.Point(lb.x, lb.y)
        for lb in basemap.labels
        if FLOWERBED_PHRASE.search(lb.text.strip().upper())
    ]
    shaped = [
        (area, f.object_class)
        for f in basemap.features
        if f.object_class in _BED_CLASSES
        for part in shapely.get_parts(f.geometry)
        if (area := _closed(part)) is not None and BED_MIN_M2 <= area.area <= FLOWERBED_MAX_M2
    ]
    if not shaped:
        return None
    areas = [area for area, _ in shaped]
    beds = _marked_rounds(basemap, shaped)
    if not names:
        return shapely.union_all(beds) if beds else None
    tree = shapely.STRtree(areas)
    for point in names:
        near = [
            areas[int(i)]
            for i in tree.query(point, predicate="dwithin", distance=BED_LABEL_REACH_M)
        ]
        holding = [a for a in near if a.buffer(BED_LABEL_REACH_M).contains(point)]
        if holding:
            bed = min(holding, key=lambda a: a.area)
            # Карта упрощает контур (допуск 0,3 м), и круг клумбы выходил многоугольником.
            rounded = bed.buffer(-BED_ROUND_M).buffer(BED_ROUND_M)
            beds.append(rounded if rounded.area >= BED_ROUND_KEEP * bed.area else bed)
    return shapely.union_all(beds) if beds else None


def _marked_rounds(
    basemap: Basemap, shaped: list[tuple[BaseGeometry, ObjectClass]]
) -> list[BaseGeometry]:
    """Круглые контуры со знаком газона внутри - круглые клумбы без подписи.

    Съёмка рисует круглую клумбу тем же пунктирным кругом, что и клумбу с подписью, а внутрь
    ставит знак травяного покрова: у парковки дома на Харьковской такой круг стоял посреди
    газона и в 3D не был виден (пользователь, 19.10.2026: «круглое зелёное пространство для
    клумбы»). Сам газон кругом не считается: контур не класса газона, круглый, не больше
    ROUND_BED_MAX_M2."""
    marks = [
        f.geometry
        for f in basemap.features
        if f.object_class is ObjectClass.LAWN and f.geometry.geom_type == "Point"
    ]
    if not marks:
        return []
    tree = shapely.STRtree(marks)
    beds = []
    for area, cls in shaped:
        if cls is ObjectClass.LAWN or area.area > ROUND_BED_MAX_M2:
            continue
        if 4 * np.pi * area.area / (area.length**2) < ROUND_BED_MIN:
            continue
        if not len(tree.query(area, predicate="contains")):
            continue
        rounded = area.buffer(-BED_ROUND_M).buffer(BED_ROUND_M)
        beds.append(rounded if rounded.area >= BED_ROUND_KEEP * area.area else area)
    return beds


def _closed(geometry: BaseGeometry) -> BaseGeometry | None:
    """Площадь замкнутого контура: полигон или кольцо линии, концы которого сходятся ближе
    BED_CLOSE_M (контур клумбы на Харьковской недозамкнут на 11 см); None - контур открыт."""
    if geometry.geom_type == "Polygon":
        return geometry
    if (
        geometry.geom_type == "LineString"
        and len(geometry.coords) > 3  # noqa: PLR2004 - кольцу нужны три вершины
        and shapely.Point(geometry.coords[0]).distance(shapely.Point(geometry.coords[-1]))
        <= BED_CLOSE_M
    ):
        area = shapely.make_valid(shapely.Polygon(geometry.coords))
        return area if area.geom_type == "Polygon" and area.area > 0 else None
    return None


def _islands_off_drawn(
    islands: BaseGeometry | None, exact: BaseGeometry | None
) -> BaseGeometry | None:
    """Острова газона, которые не режут контур покрытия чертежа сбоку.

    Полоса газона между площадкой и оградой на Харьковской заходит на край площадки на 10-20
    см и проходит как остров среди покрытия: остров вырезал из площадки углы. Газон больше
    чем наполовину вне контура чертежа - край, а не клумба: из контура он не вырезается.
    Клумба посреди площади лежит в контуре целиком и вырезается, как раньше."""
    if islands is None or exact is None or exact.is_empty:
        return islands
    parts = shapely.get_parts(islands)
    inside = _overlap_areas(parts, exact) / shapely.area(parts)
    kept = [
        part if share >= ISLAND_INSIDE_DRAWN_SHARE else _areal(part.difference(exact))
        for part, share in zip(parts, inside, strict=True)
    ]
    kept = [g for g in kept if not g.is_empty]
    return shapely.union_all(kept) if kept else None


def _overlap_areas(
    shapes: Sequence[BaseGeometry] | np.ndarray, area: BaseGeometry | None
) -> np.ndarray:
    """Площадь каждой фигуры под area. Мерится по кускам area рядом с фигурой (_subdivided):
    пересечение малого контура с покрытием всей улицы проходит по всем его вершинам, и на
    Фрунзенской (13 тыс. газонов) surface.json считался час (19.10.2026)."""
    shapes = np.asarray(shapes, dtype=object)
    out = np.zeros(len(shapes))
    pieces = np.asarray(_subdivided(area), dtype=object)
    if not len(shapes) or not len(pieces):
        return out
    near, piece = shapely.STRtree(pieces).query(shapes, predicate="intersects")
    try:
        areas = shapely.area(shapely.intersection(shapes[near], pieces[piece]))
    except shapely.errors.GEOSException:
        areas = np.array(
            [_intersection_area(shapes[i], pieces[j]) for i, j in zip(near, piece, strict=True)]
        )
    np.add.at(out, near, areas)
    return out


def _intersection_area(a: BaseGeometry, b: BaseGeometry) -> float:
    """Площадь пересечения. GEOS на сложном покрытии улицы бывает падает («Ring edge missing»,
    Харьковский проезд 19.10.2026): тогда - на сетке 1 мм, а если и там нет - 0."""
    for grid in (0.0, ISLAND_GRID_M):
        try:
            x, y = (shapely.set_precision(g, grid) if grid else g for g in (a, b))
            return float(shapely.area(shapely.intersection(x, y)))
        except shapely.errors.GEOSException:
            continue
    return 0.0


def _subdivided(area: BaseGeometry | None) -> list[BaseGeometry]:
    """Площадь кусками не больше SUBDIVIDE_VERTICES вершин: рамка куска делится пополам по
    длинной стороне, пока вершин много (как ST_Subdivide в PostGIS). Куски не перекрываются,
    их сумма - исходная площадь."""
    if area is None or area.is_empty:
        return []
    out: list[BaseGeometry] = []
    stack = [p for p in shapely.get_parts(shapely.get_parts(area)) if p.geom_type == "Polygon"]
    while stack:
        g = stack.pop()
        x0, y0, x1, y1 = g.bounds
        if (
            shapely.get_num_coordinates(g) <= SUBDIVIDE_VERTICES
            or max(x1 - x0, y1 - y0) < SUBDIVIDE_MIN_M
        ):
            out.append(g)
            continue
        if x1 - x0 >= y1 - y0:
            xm = (x0 + x1) / 2
            halves = (shapely.box(x0, y0, xm, y1), shapely.box(xm, y0, x1, y1))
        else:
            ym = (y0 + y1) / 2
            halves = (shapely.box(x0, y0, x1, ym), shapely.box(x0, ym, x1, y1))
        try:
            cut = [g.intersection(h) for h in halves]
        except shapely.errors.GEOSException:
            out.append(g)
            continue
        parts = shapely.get_parts(shapely.get_parts(cut))
        stack.extend(p for p in parts if p.geom_type == "Polygon")
    return out


def _tidy(area: BaseGeometry | None) -> BaseGeometry | None:
    """Снять пилу и щепки края газона: вычитание покрытия из газона, у которых края чертежа
    разошлись на сантиметры, давало зубцы через каждые полметра, и в 3D край газона шёл
    волной (пользователь, 19.10.2026: «меня бесит волнистость»). Размыкание на SOIL_TIDY_M
    убирает щепки, упрощение с тем же допуском - пилу."""
    if area is None or area.is_empty:
        return area
    r = SOIL_TIDY_M
    opened = _areal(area.buffer(-r, join_style="mitre").buffer(r, join_style="mitre"))
    return _simplified(opened.intersection(_areal(area)), r)


def _snap_to_faces(
    paved: BaseGeometry | None, soil: BaseGeometry | None, basemap: Basemap | None
) -> tuple[BaseGeometry | None, BaseGeometry | None]:
    """Растровые покрытие и грунт по граням линий чертежа.

    Грани - polygonize линий-разделителей подосновы (ограда, борт, край покрытия, стены,
    контуры полигонов покрытий) вместе с рамкой подосновы. Грань, где одного материала растра
    не меньше FACE_MAJORITY, отдаётся этому материалу целиком; где растр молчит или спорит,
    остаётся растр. Здания не закрашиваются.
    """
    if basemap is None or (paved is None and soil is None):
        return paved, soil
    lines = [
        f.geometry.boundary if f.geometry.geom_type in {"Polygon", "MultiPolygon"} else f.geometry
        for f in basemap.features
        if f.object_class.is_surface_barrier and f.object_class is not ObjectClass.WORK_BOUNDARY
    ]
    lines = [g for g in lines if not g.is_empty and g.geom_type in _FACE_LINE_TYPES]
    if not lines:
        return paved, soil
    frame = shapely.box(*basemap.bbox).boundary
    noded = shapely.union_all([*lines, frame])
    faces = shapely.get_parts(shapely.polygonize(shapely.get_parts(noded)))
    faces = faces[shapely.area(faces) >= FACE_MIN_M2]
    if not len(faces):
        return paved, soil
    houses = _class_area(basemap.features, ObjectClass.BUILDING)
    area = shapely.area(faces)
    share_p = _overlap_areas(faces, paved) / area
    share_s = _overlap_areas(faces, soil) / area
    inside_house = _overlap_areas(faces, houses) / area > FACE_MAJORITY
    to_paved = (share_p >= FACE_MAJORITY) & (share_p >= share_s) & ~inside_house
    to_soil = (share_s >= FACE_MAJORITY) & (share_s > share_p) & ~inside_house
    decided = shapely.union_all(faces[to_paved | to_soil])
    snapped_paved = shapely.union_all([_without(paved, decided), *faces[to_paved]])
    snapped_soil = shapely.union_all([_without(soil, decided), *faces[to_soil]])
    snapped_soil = _without(snapped_soil, snapped_paved)
    return (
        None if snapped_paved.is_empty else snapped_paved,
        None if snapped_soil is None or snapped_soil.is_empty else snapped_soil,
    )


def _paved_parts(
    paved: BaseGeometry | None, basemap: Basemap | None, exact: BaseGeometry | None = None
) -> tuple[list[BaseGeometry], list[str]]:
    """Покрытие по частям: проезжая часть, асфальтовый тротуар, плитка или неизвестное.

    На 3D проезжая часть ниже тротуара на высоту борта, а тротуар и плитка различаются
    фактурой (пользователь, 17.10.2026). Решает чертёж: полигон проезжей части (класс road) -
    проезд, тротуара (sidewalk) - не проезд; подпись съёмки внутри части - материал («ПЛ» -
    плитка, «А» - асфальт); без этого полоса шире ROAD_MIN_WIDTH_M без плитки - проезд.
    exact - покрытие, заданное контурами чертежа: его край идёт по чертежу (_drawn_edges)."""
    simple = _simplified(paved, SURFACE_AREA_TOLERANCE_M)
    if simple is None:
        return [], []
    # Контуры целиком, не куски _subdivided: швы кусков после склейки оставляли в части щели.
    exact_pieces = shapely.get_parts(exact) if exact is not None else np.asarray([], dtype=object)
    exact_tree = shapely.STRtree(exact_pieces) if len(exact_pieces) else None
    features = basemap.features if basemap is not None else ()
    drawn_roads = _class_area(features, ObjectClass.ROAD)
    drawn_walks = _class_area(features, ObjectClass.SIDEWALK)
    labels = basemap.labels if basemap is not None else ()
    pieces: list[tuple[BaseGeometry, str | None]] = []
    if drawn_roads is not None:
        pieces.append((simple.intersection(drawn_roads), PAVED_ROAD))
        simple = simple.difference(drawn_roads)
    pieces.append((simple, None))
    parts: list[BaseGeometry] = []
    kinds: list[str] = []
    for area, fixed in pieces:
        # Сглаживается каждая часть отдельно: щель между частями - линия борта, замыкание всего
        # покрытия разом склеило бы плиточную площадку с проездом.
        for raw in shapely.get_parts(area):
            near = exact_tree.query(raw, predicate="intersects") if exact_tree is not None else []
            # Части объединения не перекрываются: мультиполигон без склейки.
            own = shapely.multipolygons(exact_pieces[near]) if len(near) else None
            for part in shapely.get_parts(_drawn_edges(raw, own)):
                if part.geom_type != "Polygon" or part.area < SURFACE_MIN_PART_M2:
                    continue
                parts.append(part)
                kinds.append(fixed or _paved_kind(part, labels, drawn_walks))
    drawn = basemap.paved_polygons if basemap is not None else ()
    parts, kinds = _special_bodies(parts, kinds, labels, drawn)
    return parts, _walks(kinds)


def _special_bodies(
    parts: list[BaseGeometry],
    kinds: list[str],
    labels: Sequence[Any],
    drawn: Sequence[BaseGeometry] = (),
) -> tuple[list[BaseGeometry], list[str]]:
    """Резина - тело площадки, а не дорожки, вошедшие в неё через калитку, и не сеть
    тротуаров, с которой она соединена: часть покрытия одна, но размыкание на SPECIAL_PATH_M
    отделяет дорожки уже 2 x SPECIAL_PATH_M. Тело с подписью площадки - спецпокрытие,
    остальное - по подписям без подписей площадки."""
    r = SPECIAL_PATH_M
    plain = [lb for lb in labels if not SPECIAL_PHRASE.search(lb.text.strip().upper().rstrip("."))]
    special = [lb for lb in labels if SPECIAL_PHRASE.search(lb.text.strip().upper().rstrip("."))]
    drawn_arr = np.asarray(drawn, dtype=object)
    drawn_tree = shapely.STRtree(drawn_arr) if len(drawn_arr) else None
    out_parts: list[BaseGeometry] = []
    out_kinds: list[str] = []
    for part, kind in zip(parts, kinds, strict=True):
        inside = [lb for lb in special if shapely.contains_xy(part, lb.x, lb.y)]
        if not inside:
            out_parts.append(part)
            out_kinds.append(kind)
            continue
        bodies = _drawn_bodies(part, inside, drawn_arr, drawn_tree)
        # Подписи площадок вне контуров чертежа (спортплощадка за дорожкой от обведённой
        # площадки, Харьковская) ищут тело размыканием остатка части.
        left = [lb for lb in inside if not any(shapely.contains_xy(b, lb.x, lb.y) for b in bodies)]
        if left:
            rest_part = _areal(part.difference(shapely.union_all(bodies))) if bodies else part
            opened = _areal(rest_part.buffer(-r, join_style="mitre").buffer(r, join_style="mitre"))
            bodies += [
                body
                for body in shapely.get_parts(_areal(opened.intersection(rest_part)))
                if body.geom_type == "Polygon"
                and any(shapely.contains_xy(body, lb.x, lb.y) for lb in left)
            ]
        body = shapely.union_all(bodies) if bodies else None
        # Площадка в большой сети тротуаров голосованием проигрывает «А» дорожек; её тело с
        # подписью площадки - резина. Не отделилось (тело - почти вся часть) - решили голоса,
        # но только если в самом теле есть подпись материала: «А» на дорожке к спортплощадке
        # не делает её асфальтом (Харьковская, 19.10.2026).
        contested = body is not None and _label_material(body, plain) is not None
        if body is None or (
            kind != PAVED_SPECIAL and contested and body.area > SPECIAL_BODY_SHARE * part.area
        ):
            out_parts.append(part)
            out_kinds.append(kind)
            continue
        out_parts.extend(bodies)
        out_kinds.extend([PAVED_SPECIAL] * len(bodies))
        for rest in shapely.get_parts(_areal(part.difference(body))):
            if rest.geom_type == "Polygon" and rest.area >= SURFACE_MIN_PART_M2:
                out_parts.append(rest)
                out_kinds.append(_label_material(rest, plain) or PAVED_UNKNOWN)
    return out_parts, out_kinds


def _drawn_bodies(
    part: BaseGeometry,
    inside: Sequence[Any],
    drawn: np.ndarray,
    tree: shapely.STRtree | None,
) -> list[BaseGeometry]:
    """Тело площадки по её контуру в чертеже: полигон тротуара с подписью площадки внутри.

    Размыкание на SPECIAL_PATH_M оставляло на стыке с дорожкой у калитки клин резины и
    срезало скругление угла (Харьковская, площадка у дома 1А, 19.10.2026). Контура нет -
    пусто, и тело ищет размыкание."""
    if tree is None:
        return []
    points = shapely.points([(lb.x, lb.y) for lb in inside])
    _, hit = tree.query(points, predicate="within")
    if not len(hit):
        return []
    try:
        body = _areal(part.intersection(shapely.union_all(drawn[np.unique(hit)])))
    except shapely.errors.GEOSException:
        return []
    return [
        g
        for g in shapely.get_parts(body)
        if g.geom_type == "Polygon"
        and g.area >= SURFACE_MIN_PART_M2
        and any(shapely.contains_xy(g, lb.x, lb.y) for lb in inside)
    ]


def _walks(kinds: list[str]) -> list[str]:
    """Материал тротуара - целиком по части, а не по пикселю, и по подписи съёмки: «А» -
    асфальт, «ПЛ», «Б» - плитка; без подписи - асфальт. 3D раньше делил покрытие по ширине
    попиксельно, и граница плитки и асфальта шла пятнами («то, что идёт с бордюром, меняется
    с асфальта на тротуар», 19.10.2026); потом узкий асфальт у борта стал плиткой, а на
    панорамах Харьковской он асфальт («пофикси везде траблы с асфальтом», 19.10.2026). Плитку
    съёмка подписывает всегда, поэтому без подписи - асфальт."""
    return [PAVED_ASPHALT if kind == PAVED_UNKNOWN else kind for kind in kinds]


def _drawn_edges(raw: BaseGeometry, exact: BaseGeometry | None) -> BaseGeometry:
    """Часть покрытия после сглаживания, но с краем по контуру чертежа там, где он есть.

    _smoothed выпрямляет пилу растра упрощением на полметра, и скругления углов из чертежа
    становились срезами и острыми углами (Харьковская, площадка у дома 1А, пользователь
    19.10.2026: «странные и кривые углы у площадки»). Внутри контуров чертежа часть идёт по
    чертежу, выемки и щели уже 2 x DRAWN_JOG_M заливаются; дуги остаются. Снаружи -
    сглаженный растр без щепок уже 2 x DRAWN_SLIVER_M."""
    smooth = _smoothed(raw)
    if exact is None or exact.is_empty:
        return smooth
    try:
        own = _areal(raw.intersection(exact))
        if own.is_empty:
            return smooth
        # Контур чертежа берётся как есть: размыкание растра на полметра срезало у края
        # площадки полосу за волосяной щелью (дом 1А), а выемки и щели заливает замыкание ниже.
        kept = own
        r = DRAWN_SLIVER_M
        rest = _areal(smooth.difference(exact))
        rest = _areal(rest.buffer(-r, join_style="mitre").buffer(r, join_style="mitre"))
        merged = _areal(shapely.union_all([kept, rest]))
        # Шов двух половин и снятые узкие места внутри контура оставляли в части волосяные
        # щели и дырочки: размыкание площадки (_special_bodies) раздувало их в клинья.
        e = DRAWN_SEAM_M
        merged = _areal(merged.buffer(e, join_style="mitre").buffer(-e, join_style="mitre"))
        # Зацепы контура чертежа внутрь в 10-30 см (площадка у дома 1А) ломали садовый борт
        # ступенькой: выемки уже 2 x DRAWN_JOG_M заливаются, дуги остаются. Выступы наружу
        # уже сняло размыкание в _smoothed.
        j = DRAWN_JOG_M
        merged = _areal(merged.buffer(j, quad_segs=8).buffer(-j, quad_segs=8))
        # Шов и швы буфера оставляли на углах изломы по 1-2 см: 3D снимало вершины у таких
        # звеньев и срезало узкий вырез газона у ограды дома 1А. Дуги чертежа допуск не трогает.
        holes_free = _without_small_holes(merged, DRAWN_HOLE_M2)
        return _simplified(holes_free, DRAWN_SIMPLIFY_M) or holes_free
    except shapely.errors.GEOSException:
        return smooth


def _off_drawn_slivers(
    simplified: BaseGeometry | None, raster: BaseGeometry | None, exact: BaseGeometry | None
) -> BaseGeometry | None:
    """Выпрямленный растр без клиньев, которые упрощение вынесло за контур чертежа.

    Растр выпрямляется с допуском в полторы клетки, и у вогнутого угла контура чертежа хорда
    упрощения выходила за контур клином до 0,8 м: угол площадки срезался наискось
    (Харьковская, 19.10.2026). Клин - площадь, которой нет ни в растре, ни в контуре, и
    которая касается контура: она снимается. Покрытие растра рядом с контуром остаётся."""
    if simplified is None or simplified.is_empty or exact is None or exact.is_empty:
        return simplified
    try:
        added = _areal(simplified.difference(shapely.union_all([raster, exact])))
        pieces = shapely.get_parts(added)
        if not len(pieces):
            return simplified
        drawn = shapely.get_parts(exact)
        touching, _ = shapely.STRtree(drawn).query(pieces, predicate="dwithin", distance=1e-3)
        if not len(touching):
            return simplified
        return _without(simplified, shapely.union_all(pieces[np.unique(touching)]))
    except shapely.errors.GEOSException:
        return simplified


def _without_small_holes(area: BaseGeometry, limit_m2: float) -> BaseGeometry:
    """Площадь без дыр меньше limit_m2 (острова газона больше: клумба - десятки м²)."""
    polygons = []
    for polygon in shapely.get_parts(area):
        if polygon.geom_type != "Polygon":
            continue
        holes = [h for h in polygon.interiors if shapely.Polygon(h).area >= limit_m2]
        polygons.append(shapely.Polygon(polygon.exterior, holes))
    return shapely.union_all(polygons) if polygons else area


def _smoothed(area: BaseGeometry, *, simplify: bool = True) -> BaseGeometry:
    """Снять зубцы и закрыть выемки уже PAVED_SMOOTH_M x 2 (размыкание и замыкание с
    прямыми углами), выпрямить пилу с тем же допуском: лесенка разлива давала на краю проезда
    рваный борт, углы остаются. Радиус больше полуметра нельзя: он стирает узкий тротуар;
    сглаживание для 3D выполняется на стороне отображения."""
    r = PAVED_SMOOTH_M
    opened = area.buffer(-r, join_style="mitre").buffer(r, join_style="mitre")
    closed = opened.buffer(r, join_style="mitre").buffer(-r, join_style="mitre")
    # Замыкание только заполняет выемки: наружу за исходный контур оно не выходит.
    notches = area.buffer(r, join_style="mitre").buffer(-r, join_style="mitre")
    # Пила из зубцов в полметра (стенка выемки, Камчатская) переживает срез и заливку с
    # прямыми углами: она выпрямляется упрощением с тем же допуском, дуги потом скругляет
    # _round_turns. Буфер с прямыми углами бывает самопересекающимся (Олимпийская деревня): GEOS
    # тогда роняет пересечение, поэтому оба контура сперва чинятся до площадных частей.
    result = _areal(closed).intersection(_areal(notches))
    return (_simplified(result, r) if simplify else result) or shapely.Polygon()


def _areal(geometry: BaseGeometry) -> BaseGeometry:
    """Площадные части исправленной геометрии: make_valid даёт и линии, и точки."""
    if geometry.is_valid:
        return geometry
    fixed = shapely.make_valid(geometry)
    parts = [p for p in shapely.get_parts(fixed) if p.geom_type in {"Polygon", "MultiPolygon"}]
    return shapely.union_all(parts) if parts else shapely.Polygon()


def _paved_kind(part: BaseGeometry, labels: Sequence[Any], walks: BaseGeometry | None) -> str:
    material = _label_material(part, labels)
    if material in {PAVED_PAVERS, PAVED_SPECIAL}:
        return material
    if walks is not None and part.intersection(walks).area >= part.area / 2:
        return material or PAVED_UNKNOWN
    width = 2 * shapely.maximum_inscribed_circle(part, 0.25).length
    if width >= ROAD_MIN_WIDTH_M:
        return PAVED_ROAD
    return material or PAVED_UNKNOWN


def _label_material(part: BaseGeometry, labels: Sequence[Any]) -> str | None:
    """Материал части по подписям съёмки внутри неё: большинство решает."""
    # Порядок - приоритет при равенстве голосов: подпись площадки говорит о самой части,
    # а «А» в ней часто от соседних дорожек (площадка у дома 1А на Харьковской: 2 на 2).
    votes = {PAVED_SPECIAL: 0, PAVED_PAVERS: 0, PAVED_ASPHALT: 0}
    if not labels:
        return None
    shapely.prepare(part)
    for label in labels:
        text = label.text.strip().upper().rstrip(".")
        kind = (
            PAVED_SPECIAL
            if SPECIAL_PHRASE.search(text)
            else PAVED_PAVERS
            if text in PAVERS_LABELS or PAVERS_PHRASE.search(text)
            else PAVED_ASPHALT
            if text in ASPHALT_LABELS or "АСФАЛЬТ" in text
            else None
        )
        if kind and shapely.contains_xy(part, label.x, label.y):
            votes[kind] += 1
    best = max(votes, key=lambda k: votes[k])
    return best if votes[best] else None


def _class_area(features: Sequence[Any], object_class: ObjectClass) -> BaseGeometry | None:
    areas = [
        f.geometry
        for f in features
        if f.object_class is object_class
        and f.geometry.geom_type in {"Polygon", "MultiPolygon"}
        # Навес пунктиром - над землёй, а не дом: покрытие под ним продолжается.
        and not (object_class is ObjectClass.BUILDING and getattr(f, "dashed", False))
    ]
    return shapely.union_all(areas) if areas else None


def _polygon_rings(polygon: BaseGeometry) -> list[list[list[float]]]:
    outer = _ring_points(_round_turns(polygon.exterior.coords))
    holes = [_ring_points(_round_turns(ring.coords)) for ring in polygon.interiors]
    # Дыра в несколько сантиметров после снятия коротких звеньев - уже не кольцо.
    return [outer, *(h for h in holes if len(h) >= RING_MIN_POINTS)]


def _ring_points(coords: Sequence[tuple[float, float]]) -> list[list[float]]:
    """Вершины кольца в сантиметрах без звеньев короче RING_MIN_SEG_M: после округления и
    пересечений соседние точки совпадали или стояли в 1-2 см, а 3D снимало вершины у таких
    звеньев каскадом и срезало по ним узкий вырез газона у ограды дома 1А (19.10.2026)."""
    out: list[list[float]] = []
    for x, y in coords:
        point = [round(x, 2), round(y, 2)]
        if not out or math.dist(point, out[-1]) >= RING_MIN_SEG_M:
            out.append(point)
    # Кольцо замкнуто: последняя точка - первая, предпоследняя не ближе порога к ней.
    while len(out) > 2 and math.dist(out[-1], out[0]) < RING_MIN_SEG_M:  # noqa: PLR2004
        out.pop()
    if out and out[-1] != out[0]:
        out.append(list(out[0]))
    return out


def _simplified(area: BaseGeometry | None, tolerance: float) -> BaseGeometry | None:
    if area is None or area.is_empty:
        return None
    return shapely.make_valid(shapely.simplify(area, tolerance, preserve_topology=True))


def _without(area: BaseGeometry | None, cut: BaseGeometry | None) -> BaseGeometry | None:
    if area is None or area.is_empty:
        return None
    return area if cut is None or cut.is_empty else area.difference(cut)


def _round_turns(coords: Sequence[tuple[float, float]]) -> list[tuple[float, float]]:
    """Скруглить повороты замкнутого кольца срезом углов (Чайкин, два прохода): излом от 5 до
    75° - поворот дороги или дуга, разбитая упрощением на отрезки, - срезается по четверти
    соседних отрезков; прямой и острый угол (здание, площадка) остаётся углом. Поворотом
    считается излом, у которого оба звена не короче ROUND_MIN_SEG_M: пила края без линии
    чертежа (звенья по полметра) скруглением становилась волной (пользователь, 19.10.2026).
    Второй проход скругляет только точки, рождённые первым."""
    points = [(float(x), float(y)) for x, y in coords[:-1]]
    soft = [True] * len(points)
    for pass_no in range(SURFACE_ROUND_PASSES):
        if len(points) < 3:  # noqa: PLR2004 - кольцо из трёх точек
            break
        out: list[tuple[float, float]] = []
        out_soft: list[bool] = []
        for i, (vx, vy) in enumerate(points):
            px, py = points[i - 1]
            nx, ny = points[(i + 1) % len(points)]
            ax, ay, bx, by = vx - px, vy - py, nx - vx, ny - vy
            la, lb = math.hypot(ax, ay), math.hypot(bx, by)
            turn = (
                math.degrees(math.acos(max(-1.0, min(1.0, (ax * bx + ay * by) / (la * lb)))))
                if la and lb
                else 0.0
            )
            bend = (
                min(la, lb) >= ROUND_MIN_SEG_M if pass_no == 0 else soft[i]
            ) and SURFACE_ROUND_TURN_DEG[0] < turn < SURFACE_ROUND_TURN_DEG[1]
            if bend:
                # Срез - четверть стороны, но не длиннее ROUND_CUT_M: иначе у длинной стороны
                # угол съедался на метры, и прямоугольник стоянки выглядел скошенным.
                cap = ROUND_CUT_M * 0.5 ** (pass_no + 1)  # за все проходы - меньше ROUND_CUT_M
                ka = min(0.25, cap / la)
                kb = min(0.25, cap / lb)
                out.append((vx - ax * ka, vy - ay * ka))
                out.append((vx + bx * kb, vy + by * kb))
                out_soft += [True, True]
            else:
                out.append((vx, vy))
                out_soft.append(False)
        points, soft = out, out_soft
    return [*points, points[0]] if points else []


def _export_parts(
    parts: Sequence[BaseGeometry], kinds: Sequence[str]
) -> tuple[list[list[list[list[float]]]], list[str]]:
    """Части покрытия в выгрузку вместе с видами; часть, от которой после снятия коротких
    звеньев не осталось кольца, выпадает вместе со своим видом."""
    rings: list[list[list[list[float]]]] = []
    out_kinds: list[str] = []
    for part, kind in zip(*_exploded(parts, kinds), strict=True):
        polygon = _polygon_rings(part)
        if polygon and len(polygon[0]) >= RING_MIN_POINTS:
            rings.append(polygon)
            out_kinds.append(kind)
    return rings, out_kinds


def _rings(area: BaseGeometry | None) -> list[list[list[list[float]]]]:
    if area is None or area.is_empty:
        return []
    simple = shapely.simplify(area, SURFACE_AREA_TOLERANCE_M, preserve_topology=True)
    polygons = [
        _polygon_rings(polygon)
        for polygon in shapely.get_parts(simple)
        if polygon.geom_type == "Polygon" and not polygon.is_empty
    ]
    return [p for p in polygons if p and len(p[0]) >= RING_MIN_POINTS]


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


def write_workbook(path: Path, plan: Plan, rulebook: RuleBook) -> Path:
    """Книга Excel: ведомость посадочного материала и строка на каждую проверку нормы.

    Те же данные, что planting_schedule.csv и interpretations.csv, но числа - числами: их
    сортируют и суммируют в Excel без пересчёта (у Green Leaders так же).
    """
    book = Workbook()
    sheet = book.active
    sheet.title = "Ведомость"
    sheet.append(list(SCHEDULE_COLUMNS))
    rows = build_schedule(plan.placements)
    for section in SECTIONS:
        members = [row for row in rows if row.section == section]
        if not members:
            continue
        sheet.append(["", section])
        for row in members:
            sheet.append(
                [
                    row.number,
                    row.name_ru,
                    row.name_lat,
                    row.count,
                    row.stock.group,
                    row.stock.ball,
                    row.stock.pit,
                    round(row.pit_area_m2, 2),
                    "; ".join(row.conditions),
                ]
            )
    beds = [g for g in plan.lawns if g.kind is LawnKind.FLOWERBED]
    if beds:
        # Ведомость цветников: строка на многолетник, площадь и смесь цветника - в каждой.
        flowers = book.create_sheet("Цветники")
        flowers.append(["Цветник", "Смесь", "Площадь, м²", "Многолетник", "Латинское", "Шт."])
        for bed in beds:
            for name, latin, count in bed.plants:
                flowers.append(
                    [f"Ц{bed.number}", bed.mix, round(bed.area_m2, 1), name, latin, count]
                )
    checks = book.create_sheet("Проверки")
    checks.append(list(CSV_COLUMNS))
    for record in build_rows(plan, rulebook):
        checks.append([_cell(record.get(column)) for column in CSV_COLUMNS])
    book.save(path)
    return path


def _cell(value: object) -> object:
    """Текст, начинающийся с «=», Excel прочёл бы формулой (имена слоёв чужого DXF): апостроф
    впереди делает его текстом."""
    if isinstance(value, str) and value.startswith(("=", "+", "-", "@")):
        return "'" + value
    if value is None or isinstance(value, (int, float, str)):
        return value
    return str(value)


def write_result_layers(result: Path, target: Path) -> Path:
    """Только слои результата GREEN_* в координатах исходника - для подключения внешней ссылкой
    к генплану проектировщика (идея konstantikkov): файл лёгкий даже для Олимпийской деревни.

    Писатель плана сохраняет его рядом с result.dxf, пока чертёж в памяти; читать заново
    результат на сотни мегабайт приходится, только если такого файла нет.
    """
    # Сценарий пишет результат во временный скрытый файл и переименовывает его: слои тогда
    # лежат под временным именем («.result.pending_layers.dxf») и переезжают на место.
    # Слои под временным именем свежее: после правки они от новой записи, а файл под
    # итоговым именем - от прошлой (ревью 17.10.2026).
    candidates = [
        *sorted(
            result.parent.glob(f".*{RESULT_LAYERS_SUFFIX}"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        ),
        result.with_name(f"{result.stem}{RESULT_LAYERS_SUFFIX}"),
    ]
    ready = next((path for path in candidates if path.exists()), None)
    if ready is not None:
        if ready != target:
            ready.replace(target)
        return target
    return save_result_layers(ezdxf.readfile(result), target)


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
