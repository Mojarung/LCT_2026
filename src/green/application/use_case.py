"""Сценарий: чертёж -> классификация -> ограничения -> план -> DXF -> проверка целостности."""

from __future__ import annotations

import hashlib
import time
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

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
from green.application.errors import ConversionError, InputError
from green.application.explain import explain
from green.application.input_quality import require_complete_geometry
from green.application.lawns import plan_lawns
from green.application.placement import (
    MODE_CURB_HEDGE,
    MODE_LABELS,
    MODE_SHRUB_FILL,
    MODE_SHRUB_ROW,
    MODE_UNDERSTORY,
)
from green.application.portfolio import choose_plan
from green.application.quality import assess, site_of
from green.application.refine import refine_weak
from green.application.results import RunReport, StageTiming
from green.application.shrub_fill import fill_shrub_gaps
from green.application.shrub_groups import fill_shrub_groups
from green.application.shrub_rows import fill_shrub_rows
from green.application.surfaces import build_surface_map
from green.application.understory import fill_understory
from green.application.validation import (
    PlanValidation,
    drop_spacing_conflicts,
    trim_to_quotas,
    validate_plan,
)
from green.application.volumes import build_volumes

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Sequence
    from pathlib import Path

    from green.application.params import PlanParams
    from green.application.placement import PlacementStrategy
    from green.application.ports import (
        DrawingConverter,
        DrawingMerger,
        IntegrityChecker,
        InventoryCounts,
        LayerMapSource,
        PlanWriter,
        ProgressSink,
        RuleBookSource,
        SceneReader,
        SpeciesCatalog,
    )
    from green.application.results import IntegrityReport, PlanExportReport
    from green.domain.planting import Placement, Plan

RESULT_DXF = "result.dxf"
PENDING_DXF = ".result.pending.dxf"
MERGED_DXF = "merged_source.dxf"


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
    ) -> None:
        self._reader = reader
        self._converters = tuple(converters)
        self._rules = rules
        self._layers = layers
        self._species = species
        self._strategy = strategy
        self._writer = writer
        self._integrity = integrity
        self._merger = merger

    def execute(  # noqa: C901, PLR0915 - explicit pipeline and evidence gates
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
        assembly = None
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
        with watch.stage("load_config"):
            rulebook = self._rules.load()
            layer_map = self._layers.load()
            species = self._species.get(params.species_code)
        with watch.stage("read"):
            scene = self._reader.read(source, unit=params.drawing_unit)
            require_complete_geometry(scene)
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
            features = assign_diameters(scene.features, scene.labels, params.label_search_radius_m)
        # Подоснова строится до размещения и сразу уходит наружу: карта показывает чертёж,
        # пока план ещё считается. Зависит она только от классифицированных объектов.
        with watch.stage("basemap"):
            basemap = build_basemap(features, scene.labels)
            if progress is not None:
                progress.basemap(basemap)
            # Объёмы зданий для трёхмерной сцены - из тех же объектов и подписей, что и карта.
            # Отдельного этапа у них нет: на встроенном фрагменте Берзарина это 0,07 с, на
            # сцене из 560 тыс. объектов (49 копий фрагмента) - 2,8 с.
            volumes = build_volumes(features, scene.labels)
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
                )
                if params.require_soil
                else None
            )
        site = site_of(features, surface)
        inventory = request.inventory
        existing = inventory.matched if inventory else None

        def complete_variant(params: PlanParams) -> tuple[Plan, PlanValidation]:
            with watch.stage("place"):
                plan = self._strategy.plan(
                    features, scene.labels, rulebook, species, params, surface=surface
                )
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
                    plan = replace(plan, placements=renumbered)
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
            refined = refine_weak(
                plan,
                features=features,
                labels=scene.labels,
                rulebook=rulebook,
                params=params,
                site=site,
                surface=surface,
            )
            if refined.moved:
                recheck = validate_plan(
                    refined.plan,
                    features,
                    scene.labels,
                    rulebook,
                    params,
                    catalog=self._species.all(),
                    existing=existing,
                    surface=surface,
                )
                if recheck.ok:
                    plan, validation = refined.plan, recheck
        # Газон - грунт, который итоговый план оставил свободным: считается после сдвига слабых
        # мест, иначе посадочное место сдвинутой посадки легло бы на газон. Нормы посадок газон
        # не меняет, поэтому проверку плана не повторяет.
        with watch.stage("lawns"):
            plan = plan_lawns(
                plan,
                features=features,
                labels=scene.labels,
                surface=surface,
                rulebook=rulebook,
                params=params,
            )
        with watch.stage("explain"):
            plan = explain(plan, rulebook)
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
            load_notes=merge_notes,
            basemap=basemap,
            surface=surface,
            volumes=volumes,
            read_diagnostics=scene.read_diagnostics,
            validation=validation,
            export_validation=export_validation,
            assembly=assembly,
            classification=semantics,
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
            _site=site,
            _surface=surface,
            _surface_built=params.require_soil,
        )
        return replace(report, context=context)

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
        detail = "; ".join(
            f"{i.code} {','.join(i.placements[:2])} {i.rule_id}: {i.message} "
            f"({i.measured_m}/{i.required_m})"
            for i in result.issues[:8]
        )
        raise InputError(f"Финальная проверка плана: {len(result.issues)} нарушений. {detail}")


def to_dxf(
    converters: Sequence[DrawingConverter], source: Path, work_dir: Path
) -> tuple[Path, str | None]:
    """DXF отдаётся как есть, DWG конвертирует первый доступный конвертер."""
    suffix = source.suffix.lower()
    if suffix == ".dxf":
        return source, None
    if suffix != ".dwg":
        raise InputError(f"Ожидается DXF или DWG, получен {source.suffix or 'файл без расширения'}")
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
