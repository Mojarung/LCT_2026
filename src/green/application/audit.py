"""Нормоконтроль готового чертежа: посадки проектировщика проверяются теми же правилами.

Заказчик назвал нарушение отступов первой причиной возврата проектов
(docs/notes/15-organizers-qa.md, вопрос 14). Сценарий берёт чертёж с посадками, находит их по
имени слоя, меряет расстояния до сетей, зданий, бортов и остальных объектов подосновы и
возвращает по каждой посадке вердикт с нарушенными правилами и пунктами актов.

Чем нормоконтроль отличается от генерации (docs/notes/24-audit.md):

- Проверяются только правила со ссылкой на акт. Параметры проекта (`act_id: PROJECT`: сеть
  неизвестного типа, колодец, железная дорога) замечанием к чужому проекту быть не могут.
- Нераспознанные линии не считаются сетью неизвестного типа. При генерации это осторожность,
  при проверке это ложные нарушения: на чертеже проектировщика десятки служебных слоёв.
- Видовые правила (увеличение отступа для кроны шире 5 м, отступы от теплосети по родам, квоты)
  не применяются: это толкования проекта, а не строки таблицы.
- Шаг до существующих деревьев и кустарников (743-ПП, табл. 3.6.2) не проверяется: на плане
  Берзарина 224 таких «нарушения» дали деревья, посаженные на место вырубаемых, а сохраняемое
  дерево от вырубаемого на чертеже не отличить.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING

import numpy as np
import shapely

from green.application.barriers import FAR_M
from green.application.classification import (
    classification_report,
    classify_scene,
    require_classified,
)
from green.application.constraints import ConstraintIndex
from green.application.diameters import assign_diameters
from green.application.errors import InputError
from green.application.input_quality import require_complete_geometry
from green.application.params import active_distance_rules
from green.application.use_case import MERGED_DXF, Stopwatch, to_dxf
from green.application.wording import plural
from green.domain.norms import PlantingType, Severity
from green.domain.objects import ObjectClass
from green.domain.planting import CheckOutcome, Verdict

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

    from green.application.classification import ClassificationReport
    from green.application.params import PlanParams
    from green.application.ports import (
        AuditWriter,
        DrawingConverter,
        DrawingMerger,
        IntegrityChecker,
        LayerMapSource,
        RuleBookSource,
        SceneReader,
        SpeciesCatalog,
    )
    from green.application.results import IntegrityReport, StageTiming
    from green.domain.norms import DistanceRule, RuleBook
    from green.domain.objects import Feature, SourceRef
    from green.domain.planting import RuleCheck, Species

AUDIT_DXF = "audit.dxf"
PROJECT_ACT = "PROJECT"
_LAYER_TAIL = re.compile(r"[^|$]+$")
# «БересклетЕВР», «СиреньВЕНГ.», «ЯБЛОНЯ_Дек»: слово с заглавной или слово из одних заглавных.
_LAYER_WORD = re.compile(r"[А-ЯЁ][а-яё]+|[А-ЯЁ]+(?![а-яё])|[а-яё]+")
_MIN_STEM = 4
# Знак дерева и круг его кроны проектировщик ставит в одну точку: это одна посадка.
_SAME_PLANTING_M = 0.05
# Шаг до существующих растений (743-ПП, табл. 3.6.2) в нормоконтроль не входит.
_SPACING_CLASSES = frozenset({ObjectClass.EXISTING_TREE, ObjectClass.EXISTING_SHRUB})


@dataclass(frozen=True, slots=True)
class AuditRequest:
    run_id: str
    source: Path
    work_dir: Path
    profile: str
    params: PlanParams
    # Регулярное выражение для короткого имени слоя (после «$0$» и «|») с посадками.
    planting_layers: str
    # Слои, где посадка точно дерево или точно кустарник: сильнее каталога и круга кроны.
    tree_layers: str | None = None
    shrub_layers: str | None = None
    # Если род не найден в каталоге: круг кроны не меньше этого диаметра считается деревом.
    min_tree_crown_m: float = 2.0
    # Чем считать посадку без круга кроны и без рода в каталоге (блок-знак, точка).
    default_type: PlantingType = PlantingType.TREE
    extra_sources: tuple[Path, ...] = ()
    source_names: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class AuditedPlanting:
    """Одна посадка проектировщика и всё, что о ней сказали правила."""

    number: int
    planting_type: PlantingType
    type_basis: str
    x: float
    y: float
    layer: str
    ref: SourceRef
    crown_m: float | None
    verdict: Verdict
    checks: tuple[RuleCheck, ...]
    # Не пройденные правила с последствием «запрет»: это нарушения.
    violations: tuple[RuleCheck, ...]
    # Не пройденные правила с последствием «согласование»: охранная зона ВЛ.
    approvals: tuple[RuleCheck, ...]

    @property
    def with_barrier(self) -> tuple[RuleCheck, ...]:
        return tuple(c for c in self.checks if c.outcome is CheckOutcome.BARRIER)


@dataclass(frozen=True, slots=True)
class AuditReport:
    run_id: str
    source_name: str
    source_sha256: str
    profile: str
    params: PlanParams
    rulebook: RuleBook
    planting_layers: str
    plantings: tuple[AuditedPlanting, ...]
    # Объекты на слоях посадок, которые не точка и не круг: массивы и изгороди. Не проверяются.
    skipped: Mapping[str, int]
    integrity: IntegrityReport
    timings: tuple[StageTiming, ...]
    output_dxf: Path
    warnings: tuple[str, ...] = field(default=())
    classification: ClassificationReport | None = None

    @property
    def violating(self) -> tuple[AuditedPlanting, ...]:
        return tuple(p for p in self.plantings if p.violations)

    def by_rule(self) -> dict[str, int]:
        counts = Counter(c.rule_id for p in self.plantings for c in p.violations)
        return dict(counts.most_common())

    def summary(self) -> dict[str, object]:
        verdicts = Counter(p.verdict.value for p in self.plantings)
        return {
            "semantic_assignments_complete": self.classification.ready
            if self.classification
            else None,
            "plantings": len(self.plantings),
            "trees": sum(p.planting_type is PlantingType.TREE for p in self.plantings),
            "shrubs": sum(p.planting_type is PlantingType.SHRUB for p in self.plantings),
            "with_violations": len(self.violating),
            "violations": sum(len(p.violations) for p in self.plantings),
            "only_needs_approval": sum(
                1 for p in self.plantings if p.approvals and not p.violations
            ),
            "only_with_root_barrier": sum(
                1 for p in self.plantings if p.with_barrier and not p.violations
            ),
            "verdicts": dict(verdicts),
            "violations_by_rule": self.by_rule(),
            "skipped": dict(self.skipped),
            "integrity_ok": self.integrity.ok,
            "total_ms": round(sum(t.ms for t in self.timings), 1),
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True, slots=True)
class _Found:
    feature: Feature
    x: float
    y: float
    crown_m: float | None


class AuditSite:
    def __init__(  # noqa: PLR0913 - composition root passes every port explicitly
        self,
        *,
        reader: SceneReader,
        converters: Sequence[DrawingConverter],
        rules: RuleBookSource,
        layers: LayerMapSource,
        species: SpeciesCatalog,
        writer: AuditWriter,
        integrity: IntegrityChecker,
        merger: DrawingMerger | None = None,
    ) -> None:
        self._reader = reader
        self._converters = tuple(converters)
        self._rules = rules
        self._layers = layers
        self._species = species
        self._writer = writer
        self._integrity = integrity
        self._merger = merger

    def execute(self, request: AuditRequest) -> AuditReport:
        watch = Stopwatch([])
        params = request.params
        pattern = _compile(request.planting_layers)
        request.work_dir.mkdir(parents=True, exist_ok=True)

        with watch.stage("convert"):
            source = to_dxf(self._converters, request.source, request.work_dir)[0]
            extras = [
                to_dxf(self._converters, p, request.work_dir)[0] for p in request.extra_sources
            ]
        notes: tuple[str, ...] = ()
        if extras:
            if self._merger is None:
                raise InputError("Комплект из нескольких чертежей: склейка не подключена")
            with watch.stage("merge"):
                merged = self._merger.merge(
                    [source, *extras],
                    request.work_dir / MERGED_DXF,
                    unit=params.drawing_unit,
                    source_names=request.source_names
                    or tuple(str(path) for path in (request.source, *request.extra_sources)),
                )
                source, notes = merged.path, merged.notes
        with watch.stage("load_config"):
            rulebook = self._rules.load().for_sp42_edition(params.sp42_edition)
            layer_map = self._layers.load()
            typer = _PlantingTyper(request, self._species.all())
        with watch.stage("read"):
            scene = self._reader.read(source, unit=params.drawing_unit)
            require_complete_geometry(scene)
        with watch.stage("classify"):
            on_layers = [f for f in scene.features if pattern.search(_short(f.layer))]
            if not on_layers:
                raise InputError(
                    f"Слоёв с посадками по шаблону {request.planting_layers!r} в чертеже нет"
                )
            taken = {id(f) for f in on_layers}
            base = replace(scene, features=tuple(f for f in scene.features if id(f) not in taken))
            base, _ = classify_scene(base, layer_map, params)
            semantics = classification_report(base, layer_map, params)
            require_classified(semantics, params, scene=base, source=source)
            if not semantics.ready:
                notes = (
                    *notes,
                    "Семантика не уточнена: нормоконтроль неполон; см. classification.json.",
                )
            features = assign_diameters(base.features, base.labels, params.label_search_radius_m)
            found, skipped = _plantings(on_layers)
        with watch.stage("check"):
            plantings = _check(found, features, rulebook, params, typer)
        output = request.work_dir / AUDIT_DXF
        with watch.stage("write_dxf"):
            snapshot = self._writer.write(source, plantings, rulebook, output, unit_m=scene.unit_m)
        with watch.stage("verify"):
            integrity = self._integrity.check(snapshot, output)
        return AuditReport(
            run_id=request.run_id,
            source_name=request.source.name,
            source_sha256=scene.source_sha256,
            profile=request.profile,
            params=params,
            rulebook=rulebook,
            planting_layers=request.planting_layers,
            plantings=plantings,
            skipped=skipped,
            integrity=integrity,
            timings=tuple(watch.timings),
            output_dxf=output,
            warnings=(*notes, *scene.warnings, *_scope_notes(features, plantings, skipped)),
            classification=semantics,
        )


def _compile(pattern: str) -> re.Pattern[str]:
    try:
        return re.compile(pattern, re.IGNORECASE)
    except re.error as error:
        raise InputError(f"Шаблон слоёв {pattern!r} некорректен: {error}") from error


def _short(layer: str) -> str:
    """Имя слоя без префикса привязанной внешней ссылки: «file$0$Слой» и «file|Слой»."""
    match = _LAYER_TAIL.search(layer)
    return match.group(0) if match else layer


def _plain(word: str) -> str:
    return word.lower().replace("ё", "е")


class _PlantingTyper:
    """Дерево или кустарник: явный шаблон слоёв, род из каталога, круг кроны, значение по умолчанию.

    Размер круга кроны не годится первым признаком: на посадочном плане Берзарина бересклет,
    сирень и чубушник нарисованы кругами 2-3 м, как яблоня и боярышник.
    """

    def __init__(self, request: AuditRequest, catalog: Sequence[Species]) -> None:
        self._request = request
        self._trees = _compile(request.tree_layers) if request.tree_layers else None
        self._shrubs = _compile(request.shrub_layers) if request.shrub_layers else None
        kinds: defaultdict[str, set[PlantingType]] = defaultdict(set)
        for species in catalog:
            genus = _plain(species.name_ru.split()[0])
            kinds[genus].add(PlantingType.TREE if species.is_tree else PlantingType.SHRUB)
        # Род, у которого в каталоге и деревья, и кустарники, тип посадки не определяет.
        self._genera = {genus: next(iter(kind)) for genus, kind in kinds.items() if len(kind) == 1}
        self._cache: dict[str, tuple[PlantingType, str] | None] = {}

    def type_of(self, item: _Found) -> tuple[PlantingType, str]:
        layer = _short(item.feature.layer)
        if self._shrubs is not None and self._shrubs.search(layer):
            return PlantingType.SHRUB, "слой назван кустарниковым в параметрах"
        if self._trees is not None and self._trees.search(layer):
            return PlantingType.TREE, "слой назван древесным в параметрах"
        by_genus = self._by_genus(layer)
        if by_genus is not None:
            return by_genus
        request = self._request
        if item.crown_m is None:
            return request.default_type, "круга кроны нет, рода в каталоге нет: по умолчанию"
        kind = PlantingType.TREE if item.crown_m >= request.min_tree_crown_m else PlantingType.SHRUB
        return kind, f"рода в каталоге нет, круг кроны {item.crown_m:.1f} м"

    def _by_genus(self, layer: str) -> tuple[PlantingType, str] | None:
        if layer not in self._cache:
            found = {
                genus: kind
                for word in (_plain(w) for w in _LAYER_WORD.findall(layer))
                for genus, kind in self._genera.items()
                if word == genus
                or (len(word) >= _MIN_STEM and (genus.startswith(word) or word.startswith(genus)))
            }
            kinds = set(found.values())
            self._cache[layer] = (
                (next(iter(kinds)), f"род «{next(iter(found))}» по каталогу видов")
                if len(kinds) == 1
                else None
            )
        return self._cache[layer]


def _plantings(features: Sequence[Feature]) -> tuple[list[_Found], dict[str, int]]:
    """Точка посадки: точка, блок-знак или центр круга кроны. Остальное считается и пропускается."""
    found: dict[tuple[int, int], _Found] = {}
    skipped: Counter[str] = Counter()
    for feature in features:
        geometry = feature.geometry
        crown = 2 * feature.circle_radius_m if feature.circle_radius_m else None
        if geometry.geom_type == "Point":
            x, y = geometry.x, geometry.y
        elif crown is not None:
            center = geometry.centroid
            x, y = center.x, center.y
        else:
            skipped[geometry.geom_type] += 1
            continue
        key = (round(x / _SAME_PLANTING_M), round(y / _SAME_PLANTING_M))
        known = found.get(key)
        if known is None or (known.crown_m is None and crown is not None):
            found[key] = _Found(feature, x, y, crown)
    ordered = sorted(found.values(), key=lambda item: (item.feature.layer, item.x, item.y))
    return ordered, dict(skipped)


def audit_rules(
    rulebook: RuleBook, params: PlanParams, planting_type: PlantingType
) -> tuple[DistanceRule, ...]:
    """Правила отступов до объектов подосновы со ссылкой на акт.

    Не входят параметры проекта и шаг до существующих растений.
    """
    rules = active_distance_rules(rulebook, replace(params, planting_type=planting_type))
    return tuple(
        rule
        for rule in rules
        if rule.citation.act_id != PROJECT_ACT and rule.object_class not in _SPACING_CLASSES
    )


def _check(
    found: Sequence[_Found],
    features: Sequence[Feature],
    rulebook: RuleBook,
    params: PlanParams,
    typer: _PlantingTyper,
) -> tuple[AuditedPlanting, ...]:
    by_type: dict[PlantingType, list[tuple[_Found, str]]] = {
        PlantingType.TREE: [],
        PlantingType.SHRUB: [],
    }
    for item in found:
        kind, basis = typer.type_of(item)
        by_type[kind].append((item, basis))
    results: list[AuditedPlanting] = []
    for planting_type, items in by_type.items():
        if not items:
            continue
        # Барьер сокращает отступ только дереву. Высота кроны на чертеже не записана, поэтому
        # берётся расстояние для кроны 5-20 м: оно строже.
        barrier = FAR_M if params.root_barriers and planting_type is PlantingType.TREE else None
        rules = audit_rules(rulebook, params, planting_type)
        index = ConstraintIndex(
            features,
            rules,
            require_utility_data=params.require_utility_data,
            barrier_distance_m=barrier,
        )
        forbidding = {r.rule_id for r in rules if r.severity is Severity.FORBID}
        points = shapely.points([(item.x, item.y) for item, _ in items])
        batch = index.evaluate(np.asarray(points, dtype=object))
        for position, (item, basis) in enumerate(items):
            checks = batch.checks(position)
            failed = [c for c in checks if c.outcome is CheckOutcome.FAIL]
            results.append(
                AuditedPlanting(
                    number=0,
                    planting_type=planting_type,
                    type_basis=basis,
                    x=item.x,
                    y=item.y,
                    layer=item.feature.layer,
                    ref=item.feature.ref,
                    crown_m=item.crown_m,
                    verdict=batch.verdict(position),
                    checks=checks,
                    violations=tuple(c for c in failed if c.rule_id in forbidding),
                    approvals=tuple(c for c in failed if c.rule_id not in forbidding),
                )
            )
    results.sort(key=lambda p: (_short(p.layer), p.x, p.y))
    return tuple(replace(p, number=number) for number, p in enumerate(results, 1))


def _scope_notes(
    features: Sequence[Feature],
    plantings: Sequence[AuditedPlanting],
    skipped: Mapping[str, int],
) -> tuple[str, ...]:
    notes = [
        (
            "Нормоконтроль проверяет правила со ссылкой на акт для дерева и кустарника. Параметры "
            "проекта (сеть неизвестного типа, колодец, железная дорога) и видовые толкования "
            "(увеличение отступа для кроны шире 5 м, отступы от теплосети по родам) не "
            "применяются. Шаг до существующих деревьев не проверяется: сохраняемое дерево от "
            "вырубаемого на чертеже не отличить. Объекты подосновы, которые проект демонтирует "
            "(старый борт, сносимое строение), тоже не отличить: такие замечания снимает "
            "проектировщик."
        ),
    ]
    unknown = Counter(_short(f.layer) for f in features if f.object_class is ObjectClass.UNKNOWN)
    if unknown:
        notes.append(
            f"Не вошли в классификатор и в проверке не участвуют: {sum(unknown.values())} "
            f"объектов на {len(unknown)} слоях. Если среди них есть сети, нарушения у этих сетей "
            "не найдены."
        )
    guessed = sum(1 for p in plantings if "по каталогу" not in p.type_basis)
    if guessed:
        notes.append(
            f"У {guessed} {plural(guessed, 'посадки', 'посадок', 'посадок')} род в каталоге "
            "видов не найден: дерево или кустарник решено по "
            "кругу кроны или по умолчанию. Точнее: параметры tree_layers и shrub_layers."
        )
    if skipped:
        listed = ", ".join(f"{kind}: {count}" for kind, count in sorted(skipped.items()))
        notes.append(
            f"На слоях посадок пропущены объекты, которые не точка и не круг ({listed}): массивы "
            "и изгороди кустарников по контуру не проверяются."
        )
    return tuple(notes)
