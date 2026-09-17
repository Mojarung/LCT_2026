"""Сценарий: чертёж -> классификация -> ограничения -> план -> DXF -> проверка целостности."""

from __future__ import annotations

import time
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from green.application.assortment import assign_species
from green.application.classification import classify_scene, promote_unknown_lines
from green.application.diameters import assign_diameters
from green.application.errors import ConversionError, InputError
from green.application.explain import explain
from green.application.results import RunReport, StageTiming
from green.application.shrub_groups import fill_shrub_groups

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence
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
        RuleBookSource,
        SceneReader,
        SpeciesCatalog,
    )

RESULT_DXF = "result.dxf"
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

    @contextmanager
    def stage(self, name: str) -> Iterator[None]:
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

    def execute(self, request: PlanRequest) -> RunReport:
        watch = Stopwatch([])
        params = request.params
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
                merged = self._merger.merge([source, *extras], request.work_dir / MERGED_DXF)
                source, merge_notes = merged.path, merged.notes
        with watch.stage("load_config"):
            rulebook = self._rules.load()
            layer_map = self._layers.load()
            species = self._species.get(params.species_code)
        with watch.stage("read"):
            scene = self._reader.read(source, unit=params.drawing_unit)
        with watch.stage("classify"):
            scene, coverage = classify_scene(scene, layer_map)
            if params.unknown_lines_as_utility:
                scene = promote_unknown_lines(scene)
            features = assign_diameters(scene.features, scene.labels, params.label_search_radius_m)
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
        with watch.stage("explain"):
            plan = explain(plan, rulebook)
        output = request.work_dir / RESULT_DXF
        with watch.stage("write_dxf"):
            snapshot = self._writer.write(source, plan, rulebook, output, unit_m=scene.unit_m)
        with watch.stage("verify"):
            integrity = self._integrity.check(snapshot, output)
        integrity_notes: tuple[str, ...] = ()
        if integrity.unexportable:
            integrity_notes = (
                (
                    f"В исходнике {integrity.unexportable} сущностей без данных (REGION без ACIS "
                    "после конвертации DWG): ezdxf их не сохраняет, в сверку они не входят."
                ),
            )

        return RunReport(
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
        )


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
            return converter.to_dxf(source, work_dir), converter.name
    raise ConversionError("Нет доступного конвертера DWG -> DXF (LibreDWG или ODA File Converter)")
