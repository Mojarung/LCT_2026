"""Сценарий: чертёж -> классификация -> ограничения -> план -> DXF -> проверка целостности."""

from __future__ import annotations

import hashlib
import time
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from green.application.assortment import assign_species
from green.application.basemap import build_basemap
from green.application.classification import classify_scene, promote_unknown_lines
from green.application.diameters import assign_diameters
from green.application.editing import RunContext
from green.application.errors import ConversionError, InputError
from green.application.explain import explain
from green.application.input_quality import require_complete_blocks
from green.application.portfolio import choose_plan
from green.application.quality import assess, site_of
from green.application.results import RunReport, StageTiming
from green.application.shrub_groups import fill_shrub_groups
from green.application.validation import PlanValidation, validate_plan

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
    from green.domain.planting import Plan

RESULT_DXF = "result.dxf"
PENDING_DXF = ".result.pending.dxf"
MERGED_DXF = "merged_source.dxf"


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

    def execute(  # noqa: PLR0915 - сценарий перечисляет этапы подряд, так он и читается
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
        if extras:
            if self._merger is None:
                raise InputError("Комплект из нескольких чертежей: склейка не подключена")
            with watch.stage("merge"):
                merged = self._merger.merge(
                    [source, *extras], request.work_dir / MERGED_DXF, unit=params.drawing_unit
                )
                source, merge_notes = merged.path, merged.notes
        with watch.stage("load_config"):
            rulebook = self._rules.load()
            layer_map = self._layers.load()
            species = self._species.get(params.species_code)
        with watch.stage("read"):
            scene = self._reader.read(source, unit=params.drawing_unit)
            require_complete_blocks(scene)
        with watch.stage("classify"):
            scene, coverage = classify_scene(scene, layer_map)
            if params.unknown_lines_as_utility:
                scene = promote_unknown_lines(scene)
            features = assign_diameters(scene.features, scene.labels, params.label_search_radius_m)
        # Подоснова строится до размещения и сразу уходит наружу: карта показывает чертёж,
        # пока план ещё считается. Зависит она только от классифицированных объектов.
        with watch.stage("basemap"):
            basemap = build_basemap(features)
            if progress is not None:
                progress.basemap(basemap)
        site = site_of(features)

        def complete_variant(params: PlanParams) -> tuple[Plan, PlanValidation]:
            with watch.stage("place"):
                plan = self._strategy.plan(features, scene.labels, rulebook, species, params)
            with watch.stage("assort"):
                inventory = request.inventory
                plan = assign_species(
                    plan,
                    rulebook,
                    self._species.all(),
                    params,
                    inventory.matched if inventory else None,
                )
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
                    existing=inventory.matched if inventory else None,
                )
            # Индекс качества считается до объяснений: ценность посадки входит в её текст.
            with watch.stage("validate_plan"):
                validation = validate_plan(
                    plan,
                    features,
                    scene.labels,
                    rulebook,
                    params,
                    catalog=self._species.all(),
                    existing=inventory.matched if inventory else None,
                )
            with watch.stage("quality"):
                if validation.ok:
                    plan = assess(plan, site, params)
            return plan, validation

        plan, validation = choose_plan(complete_variant, params, features)
        require_valid_plan(validation)
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
                    f"В исходнике {integrity.unexportable} сущностей без данных (REGION без ACIS "
                    "после конвертации DWG): ezdxf их не сохраняет, в сверку они не входят."
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
            warnings=(*merge_notes, *scene.warnings, *plan.warnings, *integrity_notes),
            basemap=basemap,
            read_diagnostics=scene.read_diagnostics,
            validation=validation,
            export_validation=export_validation,
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
        f"добавлено вне результата {len(integrity.added_outside_result_layers)}. {detail}"
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
