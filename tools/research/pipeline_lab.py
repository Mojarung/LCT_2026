"""Стенд экспериментов с пайплайном посадок (docs/notes/30-pipeline-experiments.md).

Улица читается, склеивается и классифицируется один раз и кэшируется на диск: дальше
варианты пайплайна (что сажать, в каком порядке, что и как двигать) гоняются за минуты, и
каждый оценивается одним и тем же индексом качества. Запись DXF и сверка целостности здесь
не нужны - они не меняют план.

    uv run python tools/research/pipeline_lab.py cache 6-kamchatskaya-ulitsa
    uv run python tools/research/pipeline_lab.py run E00 E01 --streets 6-kamchatskaya-ulitsa
    uv run python tools/research/pipeline_lab.py table E00 E01

Кэш - в LAB_DIR (по умолчанию C:/Temp/claude/lab), итоги - строками JSON в
docs/notes/data/pipeline-lab.jsonl: каждая строка - эксперимент x улица x версия индекса.
"""

from __future__ import annotations

import gc
import json
import os
import pickle
import sys
import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from green.application.assortment import assign_species  # noqa: E402
from green.application.barriers import mark_barrier_options  # noqa: E402
from green.application.classification import classify_scene, promote_unknown_lines  # noqa: E402
from green.application.constraints import work_boundary  # noqa: E402
from green.application.diameters import assign_diameters  # noqa: E402
from green.application.quality import assess, evaluate, site_of  # noqa: E402
from green.application.refine import refine_weak  # noqa: E402
from green.application.shrub_groups import fill_shrub_groups  # noqa: E402
from green.application.shrub_rows import fill_shrub_rows  # noqa: E402
from green.application.surfaces import build_surface_map  # noqa: E402
from green.application.shrub_fill import fill_shrub_gaps  # noqa: E402
from green.application.understory import fill_understory  # noqa: E402
from green.bootstrap.container import build_container  # noqa: E402
from green.bootstrap.settings import Settings  # noqa: E402
from green.domain.planting import Verdict  # noqa: E402

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from green.application.params import PlanParams
    from green.application.quality.site import Site
    from green.application.surfaces import SurfaceMap
    from green.domain.objects import Feature, TextLabel
    from green.domain.planting import Plan

LAB_DIR = Path(os.environ.get("LAB_DIR", "C:/Temp/claude/lab"))
RESULTS = ROOT / "docs" / "notes" / "data" / "pipeline-lab.jsonl"
PROFILE = "strict"
# Сервис до экспериментов (23.09.2026): база стенда. Параметры закреплены явно, чтобы E00 и
# ранние эксперименты воспроизводились и после того, как умолчания сервиса поменялись.
OLD_SERVICE: dict[str, Any] = {
    "spacing_m": 6.0,
    "modes": ["alley", "lawn"],
    "curb_hedges": False,
    "understory": False,
    "hedge_species_balance": False,
    "alley_priority": 0.0,
    "quota_single_places": 1.0,
    "condition_penalty": 0.0,
    "shrub_fill": False,
    "density_admissible": False,
    "dust_admissible": False,
}
BASE_OVERRIDES: dict[str, Any] = {"shrub_groups": True, "shrub_rows": True, **OLD_SERVICE}
# Индекс v1 - как в сервисе до экспериментов; v2 (docs/notes/30): плотность по В.1 «при
# условии допустимости насаждений», пылезащита - по бортам с грунтом рядом.
V1: dict[str, Any] = {"density_admissible": False, "dust_admissible": False}
V2: dict[str, Any] = {"density_admissible": True, "dust_admissible": True}
ALL_STREETS = (
    "1-olimpiyskaya-derevnya",
    "2-peschanyy-pereulok",
    "3-3-ya-parkovaya",
    "4-harkovskaya-ulitsa",
    "5-bagritskogo-ulitsa",
    "6-kamchatskaya-ulitsa",
    "8-lodochnaya",
    "9-izmaylovskaya-ploschad",
    "10-staryy-gay-ul",
    "12-natashinskiy-pr-d-doroga-ot-ul-borisovskie-prudy-do-pr-pr",
    "13-harkovskiy-proezd",
    "14-kulikovskaya-ulitsa",
    "15-akademika-pontryagina",
    "16-ulitsa-berzarina",
    "17-gruzinskaya-m-ul",
    "18-kustanayskaya-ulitsa",
    "19-2-ya-pryadilnaya",
    "20-makeeva-s-ul",
)
# Лёгкие улицы для быстрых итераций: разные по устройству (аллея, дворы, узкая, широкая).
DEV_STREETS = (
    "6-kamchatskaya-ulitsa",
    "18-kustanayskaya-ulitsa",
    "2-peschanyy-pereulok",
    "9-izmaylovskaya-ploschad",
    "19-2-ya-pryadilnaya",
    "16-ulitsa-berzarina",
)


# --- Кэш улицы ------------------------------------------------------------------------------


@dataclass(slots=True)
class Scene:
    slug: str
    features: tuple[Feature, ...]
    labels: tuple[TextLabel, ...]
    unit_m: float


def cache_path(slug: str) -> Path:
    return LAB_DIR / "cache" / f"{slug}.pkl"


def build_cache(slug: str) -> Path:
    """Склеить комплект улицы, прочитать и классифицировать - как в PlanSite.execute."""
    container = build_container(Settings())
    street = container.streets.get(slug)
    if street is None:
        raise SystemExit(f"улицы {slug} нет в каталоге")
    params = container.profiles.load(PROFILE, BASE_OVERRIDES)
    work = LAB_DIR / "work" / slug
    work.mkdir(parents=True, exist_ok=True)
    source = street.main
    started = time.perf_counter()
    if street.extra:
        from green.infrastructure.cad.merge import EzdxfDrawingMerger  # noqa: PLC0415

        merged = EzdxfDrawingMerger().merge([street.main, *street.extra], work / "merged.dxf")
        source = merged.path
    scene = container.reader.read(source, unit=params.drawing_unit)
    scene, _ = classify_scene(scene, container.layers.load())
    if params.unknown_lines_as_utility:
        scene = promote_unknown_lines(scene)
    features = assign_diameters(scene.features, scene.labels, params.label_search_radius_m)
    path = cache_path(slug)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = Scene(slug, tuple(features), tuple(scene.labels), scene.unit_m)
    path.write_bytes(pickle.dumps(payload, protocol=pickle.HIGHEST_PROTOCOL))
    merged_dxf = work / "merged.dxf"
    if merged_dxf.exists():
        merged_dxf.unlink()
    print(
        f"{slug}: {len(features)} объектов, {len(scene.labels)} подписей, "
        f"{time.perf_counter() - started:.0f} с, {path.stat().st_size / 2**20:.0f} МБ"
    )
    return path


def load_scene(slug: str) -> Scene:
    path = cache_path(slug)
    if not path.exists():
        build_cache(slug)
    return pickle.loads(path.read_bytes())  # noqa: S301 - свой кэш


# --- Контекст прогона -----------------------------------------------------------------------


@dataclass(slots=True)
class Lab:
    """Всё, что пайплайн знает о прогоне: чертёж, нормы, каталог, параметры."""

    scene: Scene
    params: PlanParams
    container: Any
    # Линейка: параметры индекса не зависят от поправок эксперимента к размещению, иначе
    # вариант с ослабленными квотами мерил бы себя ослабленными же квотами.
    index_params: PlanParams | None = None
    rulebook: Any = None
    catalog: Any = None
    species: Any = None
    _site: Site | None = None
    _surface: SurfaceMap | None = None
    _surface_built: bool = False
    times: dict[str, float] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    @classmethod
    def of(
        cls, scene: Scene, overrides: dict[str, Any], index_overrides: dict[str, Any] | None = None
    ) -> Lab:
        container = build_container(Settings())
        params = container.profiles.load(PROFILE, {**BASE_OVERRIDES, **overrides})
        index_params = container.profiles.load(
            PROFILE, {**BASE_OVERRIDES, **V1, **(index_overrides or {})}
        )
        lab = cls(scene=scene, params=params, container=container, index_params=index_params)
        lab.rulebook = container.rules.load()
        lab.catalog = container.species.all()
        lab.species = container.species.get(params.species_code)
        return lab

    @property
    def features(self) -> tuple[Feature, ...]:
        return self.scene.features

    @property
    def labels(self) -> tuple[TextLabel, ...]:
        return self.scene.labels

    @property
    def site(self) -> Site:
        if self._site is None:
            self._site = site_of(self.features, self.surface)
        return self._site

    @property
    def surface(self) -> SurfaceMap | None:
        if not self._surface_built:
            self._surface = (
                build_surface_map(
                    self.features,
                    self.labels,
                    work_boundary(self.features),
                    self.params.surface_cell_m,
                )
                if self.params.require_soil
                else None
            )
            self._surface_built = True
        return self._surface

    @property
    def ruler(self) -> PlanParams:
        return self.index_params or self.params

    def assess(self, plan: Plan) -> Plan:
        return assess(plan, self.site, self.ruler)

    def index(self, plan: Plan) -> float | None:
        return evaluate(plan, self.site, self.ruler).index


type Stage = Callable[[Lab, Plan | None], Plan]


# --- Этапы базового пайплайна (как в PlanSite.execute) ------------------------------------


def place(lab: Lab, _plan: Plan | None) -> Plan:
    strategy = lab.container.use_case._strategy  # noqa: SLF001 - та же стратегия, что в сервисе
    return strategy.plan(lab.features, lab.labels, lab.rulebook, lab.species, lab.params)


def assort(lab: Lab, plan: Plan | None) -> Plan:
    assert plan is not None
    return assign_species(plan, lab.rulebook, lab.catalog, lab.params, None)


def shrub_groups(lab: Lab, plan: Plan | None) -> Plan:
    assert plan is not None
    return fill_shrub_groups(
        plan,
        strategy=lab.container.use_case._strategy,  # noqa: SLF001
        features=lab.features,
        labels=lab.labels,
        rulebook=lab.rulebook,
        catalog=lab.catalog,
        params=lab.params,
        existing=None,
    )


def shrub_rows(lab: Lab, plan: Plan | None) -> Plan:
    assert plan is not None
    return fill_shrub_rows(
        plan,
        features=lab.features,
        labels=lab.labels,
        rulebook=lab.rulebook,
        catalog=lab.catalog,
        params=lab.params,
        surface=lab.surface,
    )


def understory(lab: Lab, plan: Plan | None) -> Plan:
    assert plan is not None
    return fill_understory(
        plan,
        features=lab.features,
        labels=lab.labels,
        rulebook=lab.rulebook,
        catalog=lab.catalog,
        params=lab.params,
        surface=lab.surface,
    )


def shrub_fill(lab: Lab, plan: Plan | None) -> Plan:
    assert plan is not None
    return fill_shrub_gaps(
        plan,
        strategy=lab.container.use_case._strategy,  # noqa: SLF001
        features=lab.features,
        labels=lab.labels,
        rulebook=lab.rulebook,
        catalog=lab.catalog,
        params=lab.params,
        surface=lab.surface,
    )


def quality(lab: Lab, plan: Plan | None) -> Plan:
    assert plan is not None
    plan = mark_barrier_options(plan, lab.rulebook, applied=lab.params.root_barriers)
    return lab.assess(plan)


def refine(lab: Lab, plan: Plan | None) -> Plan:
    assert plan is not None
    refined = refine_weak(
        plan,
        features=lab.features,
        labels=lab.labels,
        rulebook=lab.rulebook,
        params=lab.params,
        site=lab.site,
        surface=lab.surface,
    )
    lab.notes.append(f"refine: сдвинуто {refined.moved} из {refined.weak}")
    return refined.plan


BASE: tuple[Stage, ...] = (place, assort, shrub_groups, shrub_rows, quality, refine)
# Пайплайн сервиса после экспериментов: те же этапы плюс кустарник под кронами; добор зоны и
# изгородь вдоль бортов включаются параметрами (modes, curb_hedges).
SERVICE: tuple[Stage, ...] = (
    place, assort, shrub_groups, shrub_rows, understory, shrub_fill, quality, refine
)


# --- Эксперименты ----------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Experiment:
    key: str
    title: str
    stages: tuple[Stage, ...] = BASE
    overrides: dict[str, Any] = field(default_factory=dict)
    # Версия индекса: v1 - как в сервисе; иные версии задаются параметрами индекса.
    index: str = "v1"
    index_overrides: dict[str, Any] = field(default_factory=dict)


EXPERIMENTS: dict[str, Experiment] = {}


def experiment(exp: Experiment) -> Experiment:
    EXPERIMENTS[exp.key] = exp
    return exp


def run_one(exp: Experiment, scene: Scene) -> dict[str, Any]:
    lab = Lab.of(scene, exp.overrides, exp.index_overrides)
    plan: Plan | None = None
    started = time.perf_counter()
    for stage in exp.stages:
        begin = time.perf_counter()
        plan = stage(lab, plan)
        name = getattr(stage, "__name__", str(stage))
        lab.times[name] = round(lab.times.get(name, 0.0) + time.perf_counter() - begin, 2)
    assert plan is not None
    # Итог всегда меряется линейкой эксперимента заново: этап мог оценить план иначе.
    plan = lab.assess(plan)
    return summarize(exp, scene.slug, lab, plan, time.perf_counter() - started)


def summarize(
    exp: Experiment, slug: str, lab: Lab, plan: Plan, seconds: float
) -> dict[str, Any]:
    quality = plan.quality
    assert quality is not None
    trees = sum(1 for p in plan.placements if p.planting_type.value == "tree")
    shrubs = len(plan.placements) - trees
    weak = sum(1 for v in quality.values.values() if v.delta * 1000 <= -0.005)
    flagged = sum(1 for v in quality.values.values() if v.flagged)
    forbidden = sum(1 for p in plan.placements if p.verdict is Verdict.FORBIDDEN)
    # Вторая линейка: та же, но плотность и пылезащита меряются от того, что участок вмещает.
    v2 = evaluate(plan, lab.site, replace(lab.ruler, **V2))
    return {
        "exp": exp.key,
        "title": exp.title,
        "index_version": exp.index,
        "street": slug,
        "index": quality.index,
        "gate": quality.gate,
        "terms": {t.key: t.score for t in quality.terms},
        "weights": {t.key: t.weight for t in quality.terms},
        "measures": {t.key: t.measure for t in quality.terms},
        "penalties": dict(quality.penalties),
        "index_v2": v2.index,
        "terms_v2": {t.key: t.score for t in v2.terms},
        "measures_v2": {t.key: t.measure for t in v2.terms if t.key in {"density", "dust"}},
        "placements": len(plan.placements),
        "trees": trees,
        "shrubs": shrubs,
        "weak": weak,
        "flagged": flagged,
        "forbidden": forbidden,
        "rejections": len(plan.rejections),
        "seconds": round(seconds, 1),
        "times": lab.times,
        "notes": lab.notes,
        "stamp": time.strftime("%Y-%m-%d %H:%M:%S"),
    }


def record(row: dict[str, Any]) -> None:
    RESULTS.parent.mkdir(parents=True, exist_ok=True)
    with RESULTS.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def load_results() -> list[dict[str, Any]]:
    if not RESULTS.exists():
        return []
    return [json.loads(line) for line in RESULTS.read_text(encoding="utf-8").splitlines() if line]


def latest(rows: Sequence[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    """Последняя запись по каждой паре (эксперимент, улица)."""
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        out[row["exp"], row["street"]] = row
    return out


def table(keys: Sequence[str], streets: Sequence[str] | None = None) -> str:
    rows = latest(load_results())
    streets = streets or sorted({s for (_, s) in rows}, key=_street_order)
    head = "| Улица | " + " | ".join(keys) + " |"
    lines = [head, "|---|" + "---|" * len(keys)]
    sums = dict.fromkeys(keys, 0.0)
    counts = dict.fromkeys(keys, 0)
    for street in streets:
        cells = []
        for key in keys:
            name, _, version = key.partition(":")
            row = rows.get((name, street))
            field_name = "index_v2" if version == "v2" else "index"
            value = None if row is None else row.get(field_name)
            if value is None:
                cells.append("-")
                continue
            cells.append(f"{value:.3f}")
            sums[key] += value
            counts[key] += 1
        lines.append(f"| {street} | " + " | ".join(cells) + " |")
    lines.append(
        "| **среднее** | "
        + " | ".join(f"**{sums[k] / counts[k]:.3f}**" if counts[k] else "-" for k in keys)
        + " |"
    )
    return "\n".join(lines)


def _street_order(slug: str) -> int:
    try:
        return int(slug.split("-", 1)[0])
    except ValueError:
        return 999


def main(argv: Sequence[str]) -> None:
    import lab_experiments  # noqa: F401, PLC0415 - регистрирует эксперименты

    command, *rest = argv
    if command == "cache":
        for slug in rest or ALL_STREETS:
            if cache_path(slug).exists():
                print(f"{slug}: уже в кэше")
                continue
            build_cache(slug)
            gc.collect()
        return
    streets: list[str] = []
    if "--streets" in rest:
        at = rest.index("--streets")
        streets = rest[at + 1].split(",")
        rest = rest[:at] + rest[at + 2 :]
    if command == "table":
        print(table(rest, streets or None))
        return
    if command == "run":
        chosen = streets or list(DEV_STREETS)
        if chosen == ["all"]:
            chosen = list(ALL_STREETS)
        if chosen == ["dev"]:
            chosen = list(DEV_STREETS)
        for slug in chosen:
            scene = load_scene(slug)
            for key in rest:
                exp = EXPERIMENTS[key]
                row = run_one(exp, scene)
                record(row)
                terms = " ".join(
                    f"{k}={v:.2f}" for k, v in row["terms"].items() if v is not None
                )
                print(
                    f"{key:5} {slug[:28]:28} idx={row['index']} n={row['placements']} "
                    f"t={row['trees']} s={row['shrubs']} weak={row['weak']} "
                    f"{row['seconds']:.0f}s | {terms}",
                    flush=True,
                )
            del scene
            gc.collect()
        return
    raise SystemExit(f"неизвестная команда {command}")


if __name__ == "__main__":
    # Эксперименты регистрируются в модуле pipeline_lab, а не в __main__: запускаем его.
    import pipeline_lab

    pipeline_lab.main(sys.argv[1:])
