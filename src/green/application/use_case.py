"""Сценарий: чертёж -> классификация -> ограничения -> план -> DXF -> проверка целостности."""

from __future__ import annotations

import hashlib
import logging
import re
import shutil
import time
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

import shapely

from green.application.assortment import assign_species
from green.application.barriers import mark_barrier_options
from green.application.basemap import build_basemap
from green.application.classification import (
    classification_report,
    classify_scene,
    promote_unknown_lines,
    require_classified,
)
from green.application.constraints import work_boundary
from green.application.diameters import assign_diameters
from green.application.editing import RunContext
from green.application.effect import street_effect
from green.application.errors import ConversionError, InputError
from green.application.explain import explain
from green.application.fences import bridge_fence_gaps
from green.application.gis_alignment import alignment_notes
from green.application.input_quality import (
    incomplete_geometry_note,
    require_complete_geometry,
    with_assumed_errors,
)
from green.application.insolation import ShadeMap, with_shade
from green.application.kerbs import refine_kerbs
from green.application.lawns import plan_lawns
from green.application.name_hints import NameHint, name_hints
from green.application.placement import (
    MODE_CURB_HEDGE,
    MODE_LABELS,
    MODE_SHRUB_FILL,
    MODE_SHRUB_ROW,
    MODE_UNDERSTORY,
)
from green.application.places import place_map, replace_moved_places, with_places
from green.application.portfolio import choose_plan
from green.application.project_stage import drop_edges_inside_lawn
from green.application.quality import assess, site_of
from green.application.refine import refine_weak
from green.application.results import RunReport, StageTiming
from green.application.schools import mark_schools
from green.application.shrub_fill import fill_shrub_gaps
from green.application.shrub_groups import fill_shrub_groups
from green.application.shrub_rows import fill_shrub_rows
from green.application.species_traces import with_species_traces
from green.application.surfaces import build_surface_map, display_extent
from green.application.understory import fill_understory
from green.application.validation import (
    PlanValidation,
    drop_spacing_conflicts,
    trim_note,
    trim_to_quotas,
    validate_plan,
)
from green.application.volumes import Volumes, build_volumes
from green.application.wording import counted, decimal_g
from green.application.work_area import with_work_area

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Sequence
    from pathlib import Path

    from green.application.classification import ClassificationReport
    from green.application.params import PlanParams
    from green.application.placement import PlacementStrategy
    from green.application.ports import (
        DrawingConverter,
        DrawingMerger,
        GisLayerSource,
        IntegrityChecker,
        InventoryCounts,
        LayerMapSource,
        LayerNameHinter,
        PlanWriter,
        ProgressSink,
        RuleBookSource,
        SceneReader,
        SpeciesCatalog,
    )
    from green.application.results import IntegrityReport, PlanExportReport
    from green.application.validation import ValidationIssue
    from green.domain.objects import Feature, Scene
    from green.domain.planting import Placement, Plan

# Контуры школ OSM берутся в этом поясе вокруг чертежа: дальше они в расчёт не входят.
SCHOOL_REACH_M = 300.0
RESULT_DXF = "result.dxf"
PENDING_DXF = ".result.pending.dxf"
MERGED_DXF = "merged_source.dxf"


_LOG = logging.getLogger(__name__)
# Сбои необязательного этапа на незнакомом чертеже: геометрия (GEOS, мультиполигон вместо
# полигона) и данные неожиданного вида. Остановка по входу (InputError) и нехватка памяти или
# диска сюда не входят - они останавливают прогон.
OPTIONAL_STAGE_FAILURES = (
    shapely.errors.GEOSException,
    ValueError,
    TypeError,
    AttributeError,
    IndexError,
    KeyError,
    ArithmeticError,
)


def optional_stage[T](title: str, make: Callable[[], T], fallback: T) -> tuple[T, str | None]:
    """Этап, без которого план по нормам, DXF и объяснения полны: 3D-объёмы, карта для показа,
    сдвиг слабых мест, газоны, баланс. Его сбой на чужом чертеже не роняет прогон, а
    называется предупреждением (чертёж жюри 236287.dxf, 19.10.2026)."""
    try:
        return make(), None
    except OPTIONAL_STAGE_FAILURES as exc:
        _LOG.warning("Этап %s пропущен", title, exc_info=True)
        reason = f"{type(exc).__name__}: {exc}"[:200]
        return fallback, (
            f"Этап «{title}» пропущен: на этом чертеже он не сработал ({reason}). План по нормам, "
            "DXF и объяснения от него не зависят."
        )


def _noted(scene: Scene, *notes: str | None) -> Scene:
    added = tuple(note for note in notes if note)
    return replace(scene, warnings=(*scene.warnings, *added)) if added else scene


# Посадки добавочных этапов кустарника: их можно снять ради квот, основу плана - нельзя.
_STAGE_NOTES = frozenset(
    MODE_LABELS[mode]
    for mode in (MODE_SHRUB_ROW, MODE_CURB_HEDGE, MODE_UNDERSTORY, MODE_SHRUB_FILL)
)


def _added_by_stages(placement: Placement) -> bool:
    return bool(placement.notes) and placement.notes[0] in _STAGE_NOTES


def _inventory_note(counts: InventoryCounts) -> str:
    """Что из ведомости доехало до квот, а что нет: одно число без второго ничего не значит."""
    return (
        f"Перечётка: строк {counts.rows_read}, учтено {counts.total} растений "
        f"{len(counts.matched)} пород, не опознано строк {counts.rows_unmatched}, "
        f"к вырубке {counts.rows_removed}, без количества {counts.rows_without_count}, "
        f"по роду приблизительно {len(counts.approximate)}."
    )


@dataclass(frozen=True, slots=True)
class PlanRequest:
    run_id: str
    source: Path
    work_dir: Path
    profile: str
    params: PlanParams
    # Существующие деревья по перечётной ведомости: входят в квоты разнообразия.
    inventory: InventoryCounts | None = None
    # Остальные чертежи комплекта (геоподоснова, сети, дендроплан): склеиваются с source.
    extra_sources: tuple[Path, ...] = ()
    # Original package paths/names survive upload renaming and DWG conversion.
    source_names: tuple[str, ...] = ()
    # Внешние ссылки (файл комплекта, путь), файлов которых нет в исходных данных заказчика.
    absent_references: tuple[tuple[str, str], ...] = ()
    # Дополнительные слои ГИС (GeoJSON, SHP): кадастр, зонирование, охранные зоны, data.mos.ru.
    gis_layers: tuple[Path, ...] = ()


@dataclass(slots=True)
class Stopwatch:
    timings: list[StageTiming]
    # Кому объявлять начало этапа: прогон из API показывает ход человеку, прогон из CLI - нет.
    # Тот же секундомер, что считает время, - второго списка этапов в сценарии не появляется.
    on_stage: Callable[[str], None] | None = None

    @contextmanager
    def stage(self, name: str) -> Iterator[None]:
        if self.on_stage is not None:
            self.on_stage(name)
        started = time.perf_counter()
        try:
            yield
        finally:
            self.timings.append(StageTiming(name, round((time.perf_counter() - started) * 1000, 1)))


class PlanSite:
    def __init__(  # noqa: PLR0913 - composition root passes every port explicitly
        self,
        *,
        reader: SceneReader,
        converters: Sequence[DrawingConverter],
        rules: RuleBookSource,
        layers: LayerMapSource,
        species: SpeciesCatalog,
        strategy: PlacementStrategy,
        writer: PlanWriter,
        integrity: IntegrityChecker,
        merger: DrawingMerger | None = None,
        gis: GisLayerSource | None = None,
        schools: Path | None = None,
        hinter: LayerNameHinter | None = None,
    ) -> None:
        self._gis = gis
        # Подсказки LLM по именам слоёв: только в отчёт (application/name_hints.py).
        self._hinter = hinter
        # Контуры школ и детсадов OpenStreetMap (config/gis/osm_schools_moscow.geojson).
        self._schools = schools
        self._school_outlines: tuple[Feature, ...] | None = None
        self._reader = reader
        self._converters = tuple(converters)
        self._rules = rules
        self._layers = layers
        self._species = species
        self._strategy = strategy
        self._writer = writer
        self._integrity = integrity
        self._merger = merger

    @property
    def asks_hints(self) -> bool:
        """Задана ли модель подсказок: этап llm_hints в полосе хода прогона."""
        return self._hinter is not None

    def _name_hints(self, semantics: ClassificationReport) -> tuple[tuple[NameHint, ...], str]:
        """Подсказки LLM и строка для журнала. Недоступная модель - запись в журнале, а не
        остановка прогона: подсказка план не меняет."""
        if self._hinter is None:
            return (), ""
        try:
            hints = name_hints(semantics, self._hinter)
        except (OSError, ValueError, KeyError) as error:
            return (), f"Подсказки LLM по именам слоёв недоступны: {type(error).__name__}: {error}"
        if not hints:
            return (), ""
        return hints, (
            f"Подсказки LLM ({self._hinter.model}): для {len(hints)} слоёв, которые сервис понял "
            "только по геометрии, модель предлагает другой класс - см. name_hints.json. План от "
            "подсказок не зависит; принять подсказку - назначить класс слою (layer_classes)."
        )

    def execute(  # noqa: C901, PLR0912, PLR0915 - explicit pipeline and evidence gates
        self, request: PlanRequest, progress: ProgressSink | None = None
    ) -> RunReport:
        watch = Stopwatch([], on_stage=progress.stage if progress is not None else None)
        params = request.params
        targets = {
            (request.work_dir / name).resolve() for name in (RESULT_DXF, PENDING_DXF, MERGED_DXF)
        }
        if any(path.resolve() in targets for path in (request.source, *request.extra_sources)):
            raise InputError(
                "Выходной файл совпадает с исходником; выберите другую папку результата"
            )
        request.work_dir.mkdir(parents=True, exist_ok=True)

        with watch.stage("convert"):
            source, converter = to_dxf(self._converters, request.source, request.work_dir)
            extras = [
                to_dxf(self._converters, path, request.work_dir)[0]
                for path in request.extra_sources
            ]
        merge_notes: tuple[str, ...] = ()
        gis_notes: tuple[str, ...] = ()
        assembly = None
        merged_dxf: Path | None = None
        merge_warnings: tuple[str, ...] = ()
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
                    absent_references=request.absent_references,
                )
                source, merge_notes = merged.path, merged.notes
                assembly = merged.assembly
                merge_warnings = merged.warnings
                # Результат сверяется со склеенным чертежом, а не с одним из файлов комплекта:
                # он и есть исходник для повторной сверки.
                merged_dxf = merged.path
        with watch.stage("load_config"):
            rulebook = self._rules.load().for_sp42_edition(params.sp42_edition)
            layer_map = self._layers.load()
            species = self._species.get(params.species_code)
        with watch.stage("read"):
            scene = self._reader.read(source, unit=params.drawing_unit)
            if params.strict_input:
                require_complete_geometry(scene)
            else:
                scene, assumed = with_assumed_errors(scene)
                scene = _noted(scene, incomplete_geometry_note(scene), assumed)
        with watch.stage("classify"):
            scene, coverage = classify_scene(scene, layer_map, params)
            semantics = classification_report(scene, layer_map, params)
            require_classified(semantics, params, scene=scene, source=source)
            if params.require_soil and params.surface_inference_mode == "distance":
                scene = replace(
                    scene,
                    warnings=(
                        *scene.warnings,
                        (
                            "Исследовательский режим покрытий: распространение подписей по "
                            "расстоянию не подтверждает границы грунта; требуется уточнение."
                        ),
                    ),
                )
            if not semantics.ready:
                scene = replace(
                    scene,
                    warnings=(
                        *scene.warnings,
                        (
                            "Семантика не уточнена: результат исследовательский; "
                            "неизвестные объекты могут нарушить допустимость посадок."
                        ),
                    ),
                )
            if params.unknown_lines_as_utility:
                scene = promote_unknown_lines(scene)
            publish = getattr(progress, "classification", None)
            if publish is not None:
                publish(semantics, scene, source)
            if request.gis_layers:
                scene, gis_notes = self._with_gis_layers(scene, request.gis_layers)
            features = assign_diameters(
                scene.features,
                (*scene.labels, *scene.hidden_diameter_labels),
                params.label_search_radius_m,
            )
            # Борт тротуара - край тротуара, а не проезжей части (аудит Берзарина 16.10.2026).
            # Граница покрытия съёмки внутри проектного газона - след прежнего состояния.
            features, _ = drop_edges_inside_lawn(features)
            features, kerb_note = refine_kerbs(features)
            if kerb_note:
                scene = replace(scene, warnings=(*scene.warnings, kerb_note))
            if params.osm_schools:
                features, school_note = mark_schools(features, self._outlines_near(features))
                if school_note:
                    scene = replace(scene, warnings=(*scene.warnings, school_note))
            # Пересмотры классов по контексту (борта, края внутри газона) - в отчёт классов.
            semantics = classification_report(replace(scene, features=features), layer_map, params)
            # Ограда штрихами: зазоры до метра закрываются перемычками, иначе материал от подписи
            # протекает сквозь ограду, а в 3D ограда стоит с дырами (Харьковская, 18.10.2026).
            features, bridged = bridge_fence_gaps(features)
            if bridged:
                note = f"Ограда: {bridged} зазоров до 1 м между штрихами закрыто перемычками."
                scene = replace(scene, warnings=(*scene.warnings, note))
            # Чужой чертёж без замкнутой границы работ: участок по самому чертежу, а не пустой план.
            if params.infer_work_boundary:
                features, area_note = with_work_area(features)
                scene = _noted(scene, area_note)
        # Подоснова строится до размещения и сразу уходит наружу: карта показывает чертёж,
        # пока план ещё считается. Зависит она только от классифицированных объектов.
        with watch.stage("basemap"):
            basemap, note = optional_stage(
                "подоснова для карты", lambda: build_basemap(features, scene.labels), None
            )
            if progress is not None and basemap is not None:
                progress.basemap(basemap)
            # Объёмы зданий для трёхмерной сцены - из тех же объектов и подписей, что и карта.
            # Отдельного этапа у них нет: на встроенном фрагменте Берзарина это 0,07 с, на
            # сцене из 560 тыс. объектов (49 копий фрагмента) - 2,8 с.
            volumes, volumes_note = optional_stage(
                "объёмы зданий для 3D", lambda: build_volumes(features, scene.labels), Volumes()
            )
            scene = _noted(scene, note, volumes_note)
            # Тень зданий над местами посадок: подбор не ставит светолюбивый вид в тень.
            shade = ShadeMap(volumes.buildings)
        # Подсказки LLM - после подосновы: карта не ждёт модель (на процессоре - минуты).
        hints: tuple[NameHint, ...] = ()
        if self._hinter is not None and params.llm_hints:
            with watch.stage("llm_hints"):
                hints, hint_note = self._name_hints(semantics)
                if hint_note:
                    scene = replace(scene, warnings=(*scene.warnings, hint_note))
        # Карта покрытий на прогон одна: её читают ряд кустарника у борта, подлесок, группы на
        # газоне, сдвиг слабых мест, индекс качества и карта в браузере - «как сервис понял,
        # где грунт». Параметры те же, что у размещения, поэтому и грунт тот же.
        with watch.stage("surface"):
            surface = (
                build_surface_map(
                    features,
                    scene.labels,
                    work_boundary(features),
                    params.surface_cell_m,
                    max_distance_m=params.surface_max_distance_m,
                    ambiguity_m=params.surface_ambiguity_m,
                    tree_distance_m=params.tree_seed_distance_m,
                    inference_mode=params.surface_inference_mode,
                    open_ground=params.open_ground,
                    target_stage=params.surface_target_stage,
                    source_stages=params.surface_source_stages,
                )
                if params.require_soil
                else None
            )
        # Для 3D карта покрытий шире границы работ: за границей съёмка тоже нарисована, а без
        # карты там был газон. В границе - те же правила, за ней решает только нарисованное.
        with watch.stage("surface_display"):
            boundary = work_boundary(features)
            display_surface, note = optional_stage(
                "карта покрытий для 3D",
                lambda: (
                    build_surface_map(
                        features,
                        scene.labels,
                        display_extent(boundary),
                        params.surface_cell_m,
                        max_distance_m=params.surface_max_distance_m,
                        ambiguity_m=params.surface_ambiguity_m,
                        tree_distance_m=params.tree_seed_distance_m,
                        inference_mode=params.surface_inference_mode,
                        open_ground=params.open_ground,
                        display_around=boundary,
                        target_stage=params.surface_target_stage,
                        source_stages=params.surface_source_stages,
                    )
                    if surface is not None
                    else None
                ),
                None,
            )
            scene = _noted(scene, note)
        site = site_of(features, surface, crown_m=params.existing_crown_m)
        places = place_map(features)
        inventory = request.inventory
        existing = inventory.matched if inventory else None

        def complete_variant(params: PlanParams) -> tuple[Plan, PlanValidation]:
            with watch.stage("place"):
                plan = self._strategy.plan(
                    features, scene.labels, rulebook, species, params, surface=surface
                )
                # Место посадки до подбора вида: категория В.6 у двора и улицы своя.
                plan = with_shade(with_places(plan, places), shade)
                if places.note:
                    plan = replace(plan, warnings=(*plan.warnings, places.note))
            with watch.stage("assort"):
                plan = assign_species(plan, rulebook, self._species.all(), params, existing)
                if inventory is not None:
                    plan = replace(plan, warnings=(*plan.warnings, _inventory_note(inventory)))
            with watch.stage("shrub_groups"):
                plan = fill_shrub_groups(
                    plan,
                    strategy=self._strategy,
                    features=features,
                    labels=scene.labels,
                    rulebook=rulebook,
                    catalog=self._species.all(),
                    params=params,
                    existing=existing,
                    surface=surface,
                )
            # Кустарник вдоль бортов, под кронами аллеи и на газоне ставится до проверки плана:
            # независимая проверка видит план целиком, и вариант с нарушением не проходит.
            with watch.stage("shrub_rows"):
                plan = fill_shrub_rows(
                    plan,
                    features=features,
                    labels=scene.labels,
                    rulebook=rulebook,
                    catalog=self._species.all(),
                    params=params,
                    surface=surface,
                )
            with watch.stage("understory"):
                plan = fill_understory(
                    plan,
                    features=features,
                    labels=scene.labels,
                    rulebook=rulebook,
                    catalog=self._species.all(),
                    params=params,
                    surface=surface,
                )
            with watch.stage("shrub_fill"):
                plan = fill_shrub_gaps(
                    plan,
                    strategy=self._strategy,
                    features=features,
                    labels=scene.labels,
                    rulebook=rulebook,
                    catalog=self._species.all(),
                    params=params,
                    surface=surface,
                )
            # Добавочные этапы подбирают вид каждый в своей выборке, квота же считается по
            # всему плану: лишние кусты этих этапов снимаются до проверки, основа плана цела.
            with watch.stage("quotas"):
                spaced = drop_spacing_conflicts(plan.placements, params, removable=_added_by_stages)
                kept = trim_to_quotas(
                    spaced,
                    params,
                    self._species.all(),
                    existing or {},
                    removable=_added_by_stages,
                )
                if len(kept) != len(plan.placements):
                    # Номера посадок идут подряд: снятые кусты не оставляют дыр в ведомости.
                    renumbered = tuple(replace(p, number=i) for i, p in enumerate(kept, 1))
                    removed = (
                        trim_note(plan.placements, spaced, reason="Шаг и посадочные ямы соседей"),
                        trim_note(spaced, kept),
                    )
                    warnings = (*plan.warnings, *(note for note in removed if note))
                    plan = replace(plan, placements=renumbered, warnings=warnings)
            plan = with_shade(with_places(plan, places), shade)
            with watch.stage("validate_plan"):
                validation = validate_plan(
                    plan,
                    features,
                    scene.labels,
                    rulebook,
                    params,
                    catalog=self._species.all(),
                    existing=existing,
                    surface=surface,
                )
            return plan, validation

        def score_variant(plan: Plan, params: PlanParams) -> Plan:
            # Индекс качества считается до объяснений: ценность посадки входит в её текст.
            # Портфель зовёт оценку, когда собраны все варианты: цель плотности у них общая.
            with watch.stage("quality"):
                # Барьер не ставится по умолчанию, но место, которое он спас бы, видно на
                # карте: решение за проектировщиком, а не за сервисом.
                plan = mark_barrier_options(plan, rulebook, applied=params.root_barriers)
                return assess(plan, site, params)

        plan, validation = choose_plan(complete_variant, params, features, score_variant)
        require_valid_plan(validation)
        # Слабые места - посадки впритык к норме - сервис сдвигает сам, если индекс от этого
        # растёт. Сдвинутый план принимается, только если его снова пропустила проверка.
        with watch.stage("refine"):
            refined, note = optional_stage(
                "сдвиг слабых мест",
                lambda: refine_weak(
                    plan,
                    features=features,
                    labels=scene.labels,
                    rulebook=rulebook,
                    params=params,
                    site=site,
                    surface=surface,
                ),
                None,
            )
            if note:
                plan = replace(plan, warnings=(*plan.warnings, note))
            if refined is not None and refined.moved:
                # Сдвинутая посадка - в новой точке: место и категория В.6 для проверки заново.
                moved = replace_moved_places(plan, refined.plan, places)
                recheck = validate_plan(
                    moved,
                    features,
                    scene.labels,
                    rulebook,
                    params,
                    catalog=self._species.all(),
                    existing=existing,
                    surface=surface,
                )
                if recheck.ok:
                    plan, validation = moved, recheck
                else:
                    codes = sorted({issue.code for issue in recheck.issues})
                    note = (
                        f"Сдвиг слабых мест не применён: план со сдвигами не прошёл проверку "
                        f"({', '.join(codes)}), оставлены исходные точки"
                    )
                    plan = replace(plan, warnings=(*plan.warnings, note))
        # Газон - грунт, который итоговый план оставил свободным: считается после сдвига слабых
        # мест, иначе посадочное место сдвинутой посадки легло бы на газон. Нормы посадок газон
        # не меняет, поэтому проверку плана не повторяет.
        with watch.stage("lawns"):
            lawned, note = optional_stage(
                "газоны и цветники",
                lambda: plan_lawns(
                    plan,
                    features=features,
                    labels=scene.labels,
                    surface=surface,
                    rulebook=rulebook,
                    params=params,
                ),
                plan,
            )
            plan = replace(lawned, warnings=(*lawned.warnings, note)) if note else lawned
        # Что план даёт улице: было - существующие насаждения, стало - вместе с планом.
        with watch.stage("effect"):
            effect, note = optional_stage(
                "баланс «было - стало»",
                lambda: street_effect(
                    plan, site, params, inventory, surface=surface, catalog=self._species.all()
                ),
                None,
            )
            plan = replace(
                plan,
                effect=effect,
                warnings=(*plan.warnings, note) if note else plan.warnings,
            )
        with watch.stage("explain"):
            plan = explain(with_species_traces(plan, features, rulebook, params), rulebook)
        output = request.work_dir / RESULT_DXF
        pending = request.work_dir / PENDING_DXF
        with watch.stage("write_dxf"):
            snapshot = self._writer.write(source, plan, rulebook, pending, unit_m=scene.unit_m)
        with watch.stage("verify"):
            integrity = self._integrity.check(snapshot, pending)
            export_validation = self._integrity.check_plan(pending, plan, unit_m=scene.unit_m)
            require_valid_export(integrity, export_validation)
            pending.replace(output)
        integrity_notes: tuple[str, ...] = ()
        if integrity.unexportable:
            integrity_notes = (
                (
                    f"В исходнике {integrity.unexportable} сущностей без данных (REGION без "
                    "ACIS после конвертации DWG): ezdxf их не сохраняет, в сверку они не входят."
                ),
            )
        report = RunReport(
            run_id=request.run_id,
            source_name=request.source.name,
            source_sha256=scene.source_sha256,
            dxf_version=scene.dxf_version,
            profile=request.profile,
            params=params,
            rulebook=rulebook,
            layer_map_fingerprint=layer_map.fingerprint,
            coverage=coverage,
            class_counts=dict(Counter(str(f.object_class) for f in features)),
            plan=plan,
            integrity=integrity,
            timings=tuple(watch.timings),
            output_dxf=output,
            converter=converter,
            # Журнал склейки отдельно: в сводке прогона он вытеснял то, что меняет смысл плана
            # (на улице из каталога - около сорока строк аудита планшетов). Предупреждения
            # чтения и классификации остаются в сводке: они о допустимости посадок.
            warnings=(*merge_warnings, *scene.warnings, *plan.warnings, *integrity_notes),
            load_notes=(*merge_notes, *gis_notes),
            basemap=basemap,
            surface=surface,
            display_surface=display_surface,
            volumes=volumes,
            read_diagnostics=scene.read_diagnostics,
            validation=validation,
            export_validation=export_validation,
            assembly=assembly,
            classification=semantics,
            merged_dxf=merged_dxf,
            name_hints=hints,
        )
        # Состояние для интерактивной правки собирается из того, что уже в памяти, поэтому
        # само по себе ничего не стоит. Индекс ограничений и карта покрытий строятся позже и
        # только по требованию: прогон из CLI за правку не платит.
        context = RunContext(
            run_id=request.run_id,
            features=tuple(features),
            labels=scene.labels,
            params=params,
            rulebook=rulebook,
            plan=plan,
            source=source,
            unit_m=scene.unit_m,
            report=report,
            inventory=inventory,
            _site=site,
            _surface=surface,
            _surface_built=params.require_soil,
        )
        return replace(report, context=context)

    def _outlines_near(self, features: Sequence[Feature]) -> tuple[Feature, ...]:
        """Контуры школ OSM в системе координат чертежа рядом с ним (читаются один раз)."""
        if self._schools is None or self._gis is None or not self._schools.exists():
            return ()
        if self._school_outlines is None:
            self._school_outlines = self._gis.read([self._schools]).features
        if not features or not self._school_outlines:
            return ()
        bounds = shapely.total_bounds([f.geometry for f in features])
        area = shapely.box(*bounds).buffer(SCHOOL_REACH_M)
        return tuple(f for f in self._school_outlines if f.geometry.intersects(area))

    def _with_gis_layers(
        self, scene: Scene, paths: tuple[Path, ...]
    ) -> tuple[Scene, tuple[str, ...]]:
        """Объекты слоёв ГИС встают в сцену после классификации чертежа: размещение, итоговая
        проверка плана и правка на карте видят их так же, как объекты подосновы."""
        if self._gis is None:
            raise InputError("Слои ГИС не подключены к сервису")
        layers = self._gis.read(paths)
        notes, warnings = alignment_notes(layers.features, scene.features)
        scene = replace(
            scene,
            features=(*scene.features, *layers.features),
            warnings=(*scene.warnings, *layers.warnings, *warnings),
        )
        return scene, (*layers.notes, *notes)

    def rebuild(self, context: RunContext, plan: Plan, work_dir: Path) -> RunReport:
        """Переписать DXF и отчёт по исправленному плану, не перечитывая чертёж.

        Пересчёт норм уже сделан правкой; здесь остаётся запись и сверка целостности - то
        есть ровно те шаги, которые обязаны выполниться заново, чтобы исходные слои остались
        нетронутыми, а результат соответствовал плану на экране.
        """
        if context.report is None:
            raise InputError("Прогон нельзя пересобрать: отчёт исходного прогона не сохранён")
        watch = Stopwatch([])
        output = work_dir / RESULT_DXF
        pending = work_dir / PENDING_DXF
        with watch.stage("validate_plan"):
            validation = validate_plan(
                plan,
                context.features,
                context.labels,
                context.rulebook,
                context.params,
                catalog=self._species.all(),
                existing=context.report.plan.assortment_summary.existing
                if context.report.plan.assortment_summary
                else None,
                surface=context.surface_map(),
            )
            require_valid_plan(validation)
        with watch.stage("write_dxf"):
            snapshot = self._writer.write(
                context.source, plan, context.rulebook, pending, unit_m=context.unit_m
            )
        with watch.stage("verify"):
            integrity = self._integrity.check(snapshot, pending)
            export_validation = self._integrity.check_plan(pending, plan, unit_m=context.unit_m)
            require_valid_export(integrity, export_validation)
            pending.replace(output)
        return replace(
            context.report,
            plan=plan,
            integrity=integrity,
            output_dxf=output,
            validation=validation,
            export_validation=export_validation,
            timings=tuple(watch.timings),
            warnings=(*context.report.warnings, "План изменён вручную и пересобран."),
        )


def require_valid_export(integrity: IntegrityReport, exported: PlanExportReport) -> None:
    if integrity.ok and exported.ok:
        return
    detail = "; ".join(exported.issues[:8])
    raise InputError(
        "Записанный DXF не прошёл проверку исходника/посадок: "
        f"изменено {len(integrity.changed)}, пропало {len(integrity.missing)}, "
        f"добавлено вне результата {len(integrity.added_outside_result_layers)}, "
        f"не сохраняются {integrity.unexportable}. {detail}"
    )


def require_valid_plan(result: PlanValidation) -> None:
    if not result.ok:
        detail = "; ".join(_issue_line(issue) for issue in result.issues[:8])
        count = counted(len(result.issues), "нарушение", "нарушения", "нарушений")
        raise InputError(f"Финальная проверка плана: {count}. {detail}")


def _issue_line(issue: ValidationIssue) -> str:
    """Код, посадки и правило - только непустые; замер и норма - только когда измерены."""
    head = " ".join(
        part for part in (issue.code, ", ".join(issue.placements[:2]), issue.rule_id) if part
    )
    line = f"{head}: {issue.message}"
    if issue.measured_m is not None and issue.required_m is not None:
        measured = decimal_g(round(issue.measured_m, 2))
        required = decimal_g(round(issue.required_m, 2))
        line += f" (замер {measured} м при норме {required} м)"
    return line


_DWG_MAGIC = re.compile(rb"^AC10\d\d")
_LEADING = b"\xef\xbb\xbf \t\r\n"  # BOM и пробелы перед первым кодом группы
_BINARY_DXF = b"AutoCAD Binary DXF"


def drawing_kind(source: Path) -> str | None:
    """«.dwg» или «.dxf» по первым байтам файла; None - не узнан (решает расширение)."""
    with source.open("rb") as stream:
        head = stream.read(64)
    if _DWG_MAGIC.match(head):
        return ".dwg"
    text = head.lstrip(_LEADING)
    if head.startswith(_BINARY_DXF) or text.startswith((b"0", b"999")):
        return ".dxf"
    return None


def to_dxf(
    converters: Sequence[DrawingConverter], source: Path, work_dir: Path
) -> tuple[Path, str | None]:
    """DXF отдаётся как есть, DWG конвертирует первый доступный конвертер.

    Тип решает содержимое, а не расширение: DWG, сохранённый с расширением .dxf (или DXF с
    расширением .dwg), - частая ошибка выгрузки, и чтение не должно на ней падать."""
    suffix = source.suffix.lower()
    if suffix not in {".dxf", ".dwg"}:
        raise InputError(f"Ожидается DXF или DWG, получен {source.suffix or 'файл без расширения'}")
    kind = drawing_kind(source) or suffix
    if kind == ".dxf":
        return source, None
    if suffix != ".dwg":
        # Конвертеры выбирают файлы по расширению (ODA - маска *.DWG): копия с верным именем.
        renamed = work_dir / "converted" / "renamed" / f"{source.stem}.dwg"
        renamed.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, renamed)
        source = renamed
    for converter in converters:
        if converter.available():
            # Packages often contain different drawings with the same basename.
            # A content-addressed subdirectory prevents the second conversion
            # from overwriting the already returned first path.
            with source.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            converted_dir = work_dir / "converted" / digest[:20]
            converted_dir.mkdir(parents=True, exist_ok=True)
            return converter.to_dxf(source, converted_dir), converter.name
    raise ConversionError("Нет доступного конвертера DWG -> DXF (LibreDWG или ODA File Converter)")
