"""Сборка зависимостей. Единственное место, где прикладной слой встречается с адаптерами."""

from __future__ import annotations

from dataclasses import dataclass

from green.application.audit import AuditSite
from green.application.editing import RunContextCache
from green.application.placement import GreedyPlantingStrategy
from green.application.runs import RunService
from green.application.use_case import PlanSite
from green.bootstrap.settings import Settings
from green.infrastructure.cad.audit_writer import EzdxfAuditWriter
from green.infrastructure.cad.documents import DocumentCache
from green.infrastructure.cad.integrity import EzdxfIntegrityChecker
from green.infrastructure.cad.merge import EzdxfDrawingMerger
from green.infrastructure.cad.reader import EzdxfSceneReader
from green.infrastructure.cad.writer import EzdxfPlanWriter
from green.infrastructure.config.repositories import (
    YamlLayerMapSource,
    YamlProfileSource,
    YamlRuleBookSource,
    YamlSpeciesCatalog,
)
from green.infrastructure.convert.libredwg import LibreDwgConverter
from green.infrastructure.convert.oda import OdaFileConverter
from green.infrastructure.gis.layers import YamlGisLayerSource
from green.infrastructure.inventory import read_inventory
from green.infrastructure.reports.artifacts import FileArtifactSink
from green.infrastructure.reports.audit_artifacts import AuditArtifactSink
from green.infrastructure.storage.contexts import PickleRunContextStore, code_fingerprint
from green.infrastructure.storage.runs import FileSystemRunStore
from green.infrastructure.streets import JsonStreetCatalog

type Converter = LibreDwgConverter | OdaFileConverter


@dataclass(frozen=True, slots=True)
class Container:
    settings: Settings
    use_case: PlanSite
    audit: AuditSite
    audit_artifacts: AuditArtifactSink
    runs: RunService
    store: FileSystemRunStore
    profiles: YamlProfileSource
    rules: YamlRuleBookSource
    layers: YamlLayerMapSource
    species: YamlSpeciesCatalog
    reader: EzdxfSceneReader
    documents: DocumentCache
    integrity: EzdxfIntegrityChecker
    artifacts: FileArtifactSink
    converters: tuple[Converter, ...]
    streets: JsonStreetCatalog
    # Контексты прогонов для правки на карте: живут в памяти, переживают запрос, но не рестарт.
    contexts: RunContextCache


def build_container(settings: Settings | None = None) -> Container:
    settings = settings or Settings()
    config = settings.config_dir
    rules = YamlRuleBookSource(config / "acts.yaml", config / "rules.yaml")
    layers = YamlLayerMapSource(config / "layer_map.yaml")
    species = YamlSpeciesCatalog(config / "species.yaml")
    profiles = YamlProfileSource(config / "profiles")
    documents = DocumentCache()
    reader = EzdxfSceneReader(documents=documents)
    integrity = EzdxfIntegrityChecker()
    artifacts = FileArtifactSink()
    converters = _converters(settings)
    use_case = PlanSite(
        reader=reader,
        converters=converters,
        rules=rules,
        layers=layers,
        species=species,
        strategy=GreedyPlantingStrategy(),
        writer=EzdxfPlanWriter(text_font=settings.text_font, documents=documents),
        integrity=integrity,
        merger=EzdxfDrawingMerger(),
        gis=YamlGisLayerSource(settings.config_dir / "geo_layers.yaml"),
    )
    audit = AuditSite(
        reader=reader,
        converters=converters,
        rules=rules,
        layers=layers,
        species=species,
        writer=EzdxfAuditWriter(text_font=settings.text_font, documents=documents),
        integrity=integrity,
        merger=EzdxfDrawingMerger(),
    )
    store = FileSystemRunStore(
        settings.runs_dir,
        max_bytes=round(settings.runs_max_gb * 2**30) if settings.runs_max_gb else None,
    )
    streets = JsonStreetCatalog(settings.streets_dir)
    contexts = RunContextCache(
        settings.edit_contexts,
        store=PickleRunContextStore(store, code_fingerprint())
        if settings.edit_contexts_saved
        else None,
    )
    runs = RunService(
        store=store,
        use_case=use_case,
        profiles=profiles,
        artifacts=artifacts,
        max_parallel=settings.max_parallel_runs,
        inventory=lambda path: read_inventory(path, species.all()),
        contexts=contexts,
    )
    return Container(
        settings=settings,
        use_case=use_case,
        audit=audit,
        audit_artifacts=AuditArtifactSink(),
        runs=runs,
        store=store,
        profiles=profiles,
        rules=rules,
        layers=layers,
        species=species,
        reader=reader,
        documents=documents,
        integrity=integrity,
        artifacts=artifacts,
        converters=converters,
        streets=streets,
        contexts=contexts,
    )


def _converters(settings: Settings) -> tuple[Converter, ...]:
    oda = OdaFileConverter(binary=settings.oda_binary, timeout_s=settings.converter_timeout_s)
    libredwg = LibreDwgConverter(
        binary=settings.libredwg_binary, timeout_s=settings.converter_timeout_s
    )
    choice: dict[str, tuple[Converter, ...]] = {
        "auto": (oda, libredwg),
        "oda": (oda,),
        "libredwg": (libredwg,),
        "none": (),
    }
    return choice[settings.converter]
