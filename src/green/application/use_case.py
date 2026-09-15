"""Сценарий: чертёж -> классификация -> ограничения -> план -> DXF -> проверка целостности."""

from __future__ import annotations

import time
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING

from green.application.classification import classify_scene, promote_unknown_lines
from green.application.diameters import assign_diameters
from green.application.errors import ConversionError, InputError
from green.application.explain import explain
from green.application.results import RunReport, StageTiming

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence
    from pathlib import Path

    from green.application.params import PlanParams
    from green.application.placement import PlacementStrategy
    from green.application.ports import (
        DrawingConverter,
        IntegrityChecker,
        LayerMapSource,
        PlanWriter,
        RuleBookSource,
        SceneReader,
        SpeciesCatalog,
    )

RESULT_DXF = "result.dxf"


@dataclass(frozen=True, slots=True)
class PlanRequest:
    run_id: str
    source: Path
    work_dir: Path
    profile: str
    params: PlanParams


@dataclass(slots=True)
class _Stopwatch:
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
    ) -> None:
        self._reader = reader
        self._converters = tuple(converters)
        self._rules = rules
        self._layers = layers
        self._species = species
        self._strategy = strategy
        self._writer = writer
        self._integrity = integrity

    def execute(self, request: PlanRequest) -> RunReport:
        watch = _Stopwatch([])
        params = request.params
        request.work_dir.mkdir(parents=True, exist_ok=True)

        with watch.stage("convert"):
            source, converter = self._to_dxf(request.source, request.work_dir)
        with watch.stage("load_config"):
            rulebook = self._rules.load()
            layer_map = self._layers.load()
            species = self._species.get(params.species_code)
        with watch.stage("read"):
            scene = self._reader.read(source)
        with watch.stage("classify"):
            scene, coverage = classify_scene(scene, layer_map)
            if params.unknown_lines_as_utility:
                scene = promote_unknown_lines(scene)
            features = assign_diameters(scene.features, scene.labels, params.label_search_radius_m)
        with watch.stage("place"):
            plan = self._strategy.plan(features, rulebook, species, params)
        with watch.stage("explain"):
            plan = explain(plan, rulebook)
        output = request.work_dir / RESULT_DXF
        with watch.stage("write_dxf"):
            snapshot = self._writer.write(source, plan, rulebook, output)
        with watch.stage("verify"):
            integrity = self._integrity.check(snapshot, output)

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
            warnings=(*scene.warnings, *plan.warnings),
        )

    def _to_dxf(self, source: Path, work_dir: Path) -> tuple[Path, str | None]:
        suffix = source.suffix.lower()
        if suffix == ".dxf":
            return source, None
        if suffix != ".dwg":
            raise InputError(
                f"Ожидается DXF или DWG, получен {source.suffix or 'файл без расширения'}"
            )
        for converter in self._converters:
            if converter.available():
                return converter.to_dxf(source, work_dir), converter.name
        raise ConversionError(
            "Нет доступного конвертера DWG -> DXF (LibreDWG или ODA File Converter)"
        )
