"""Газоны плана (п. 3 ТЗ, травянистые покрытия): грунт, который посадки оставили свободным.

Участок из четырёх граней между бортами. A (x 0-20) - контур слоя газона: газон по чертежу,
сохраняемый или восстанавливаемый. B (20-40) - грань с подписью «ГРУНТ»: газон устраиваемый.
C (40-60) - цветник по подписи: газоном не становится. D (60-80) - знак существующего массива:
не газон. Посадочные места деревьев и кустарников из газона вырезаются.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

import pytest
from shapely.geometry import LineString, Point, box
from test_pipeline_synthetic import ROOT, _street

from green.application.approximation import reserved_buffer
from green.application.constraints import work_boundary
from green.application.editing import Edit, EditKind, apply_edits
from green.application.explain import explain
from green.application.lawns import WARNING_PREFIX, plan_lawns
from green.application.params import PlanParams
from green.application.surfaces import build_surface_map
from green.application.use_case import PlanRequest
from green.bootstrap.container import build_container
from green.bootstrap.settings import Settings
from green.domain.norms import LawnKind, PlantingType
from green.domain.objects import Feature, ObjectClass, SourceRef, TextLabel
from green.domain.planting import LifeForm, Placement, Plan, Species, Verdict
from green.infrastructure.config.repositories import YamlRuleBookSource

if TYPE_CHECKING:
    from shapely.geometry.base import BaseGeometry

    from green.application.results import RunReport
    from green.application.surfaces import SurfaceMap

BOOK = YamlRuleBookSource(ROOT / "config" / "acts.yaml", ROOT / "config" / "rules.yaml").load()
BOUNDARY = box(0, 0, 80, 30)
LAWN_CONTOUR = box(1, 1, 19, 29)
FACE_B = box(20, 0, 40, 30)
NOT_LAWN = box(40.01, 0, 80, 30)  # цветник и массив
TREE = Species("tree", "липа", "Tilia cordata", 6.0, life_form=LifeForm.TREE_MEDIUM)
SHRUB = Species("shrub", "сирень", "Syringa vulgaris", 2.0, life_form=LifeForm.SHRUB_MEDIUM)
# Радиусы посадочных мест - из параметров проекта (яма 743-ПП, табл. 3.3.1, notes/34).
TREE_PIT_M, SHRUB_PIT_M = PlanParams().planting_radius_m, PlanParams().shrub_planting_radius_m


def _feature(cls: ObjectClass, geometry: BaseGeometry, name: str, **extra: object) -> Feature:
    ref = SourceRef("00000000", "00000000", name)
    return Feature(ref, name, geometry, object_class=cls, **extra)  # type: ignore[arg-type]


def _label(text: str, x: float, y: float) -> TextLabel:
    return TextLabel(SourceRef("00000000", "00000000", f"{text}{x}"), "labels", x, y, text)


def _placement(number: int, species: Species, x: float, y: float) -> Placement:
    kind = PlantingType.TREE if species.is_tree else PlantingType.SHRUB
    return Placement(f"P{number:05d}", number, kind, species, x, y, Verdict.ALLOWED, ())


PLAN = Plan(
    placements=(
        _placement(1, TREE, 10, 15),  # в контуре газона
        _placement(2, TREE, 30, 8),  # на грунте
        _placement(3, SHRUB, 30, 22),
        _placement(4, TREE, 50, 15),  # в цветнике
    ),
    rejections=(),
)


def _scene(
    *, boundary: bool = True, labels: tuple[TextLabel, ...] = ()
) -> tuple[list[Feature], list[TextLabel], SurfaceMap]:
    lines = [
        LineString([(0, 0), (80, 0)]),
        LineString([(80, 0), (80, 30)]),
        LineString([(80, 30), (0, 30)]),
        LineString([(0, 30), (0, 0)]),
        *(LineString([(x, 0), (x, 30)]) for x in (20, 40, 60)),
    ]
    features = [_feature(ObjectClass.CURB, line, f"curb{i}") for i, line in enumerate(lines)]
    features.append(_feature(ObjectClass.LAWN, LAWN_CONTOUR, "lawn-contour"))
    features.append(
        _feature(
            ObjectClass.EXISTING_WOODLAND,
            Point(70, 15),
            "LISTVL",
            source_entity_type="SYMBOL_MARKER",
        )
    )
    if boundary:
        features.append(_feature(ObjectClass.WORK_BOUNDARY, BOUNDARY, "boundary"))
    texts = [_label("ГРУНТ", 30, 15), _label("ЦВЕТНИК", 50, 15), *labels]
    surface = build_surface_map(features, texts, work_boundary(features), 0.5)
    assert surface is not None
    return features, texts, surface


def _lawns(params: PlanParams | None = None, **scene: object) -> tuple[Plan, SurfaceMap]:
    features, labels, surface = _scene(**scene)  # type: ignore[arg-type]
    plan = plan_lawns(
        PLAN,
        features=features,
        labels=labels,
        surface=surface,
        rulebook=BOOK,
        params=params or PlanParams(),
    )
    return plan, surface


def _pit(placement: Placement) -> float:
    return TREE_PIT_M if placement.planting_type is PlantingType.TREE else SHRUB_PIT_M


def _lawn_warnings(plan: Plan) -> list[str]:
    return [w for w in plan.warnings if w.startswith(WARNING_PREFIX)]


def test_uncertain_material_is_excluded_from_lawn_even_inside_explicit_soil() -> None:
    features, labels, surface = _scene()
    uncertain = box(2, 2, 5, 5)
    plan = plan_lawns(
        PLAN,
        features=features,
        labels=labels,
        surface=replace(surface, uncertainty_area=uncertain),
        rulebook=BOOK,
        params=PlanParams(),
    )
    assert plan.lawns
    assert sum(lawn.geometry.intersection(uncertain).area for lawn in plan.lawns) == 0
    baseline, _ = _lawns()
    before = sum(lawn.area_m2 for lawn in baseline.lawns)
    after = sum(lawn.area_m2 for lawn in plan.lawns)
    assert before - after == pytest.approx(uncertain.area)


def test_free_soil_becomes_kept_and_new_lawn() -> None:
    plan, surface = _lawns()

    assert [lawn.kind for lawn in plan.lawns] == [LawnKind.KEPT, LawnKind.NEW]
    kept, new = plan.lawns
    assert LAWN_CONTOUR.covers(kept.geometry)
    assert FACE_B.covers(new.geometry)
    pit = reserved_buffer(Point(0, 0), TREE_PIT_M).area
    shrub_pit = reserved_buffer(Point(0, 0), SHRUB_PIT_M).area
    assert kept.area_m2 == pytest.approx(LAWN_CONTOUR.area - pit, abs=0.01)
    assert new.area_m2 == pytest.approx(FACE_B.area - pit - shrub_pit, abs=0.01)
    assert surface.soil_area is not None
    for lawn in plan.lawns:
        assert BOUNDARY.covers(lawn.geometry)
        assert lawn.geometry.difference(surface.soil_area).area < 1e-6
        assert not lawn.geometry.intersects(NOT_LAWN)
        for placement in PLAN.placements:
            assert lawn.geometry.distance(Point(placement.x, placement.y)) >= _pit(placement) - 1e-6
    assert [lawn.lawn_id for lawn in plan.lawns] == ["L00001", "L00002"]
    assert [lawn.number for lawn in plan.lawns] == [1, 2]


def test_every_lawn_is_explained_by_rules_with_a_source() -> None:
    plan, _ = _lawns()
    kept, new = plan.lawns

    assert kept.rule_ids == ("R-LAWN-KEPT-001", "R-LAWN-DRAW-001")
    assert new.rule_ids == ("R-LAWN-NEW-001", "R-LAWN-DRAW-001")
    for rule_id in {*kept.rule_ids, *new.rule_ids}:
        assert BOOK.rule(rule_id) is not None
    # Сверенной цитаты о том, где устраивать газон, нет: параметр проекта, «не сверено».
    for rule_id in ("R-LAWN-KEPT-001", "R-LAWN-NEW-001"):
        citation = BOOK.rule(rule_id).citation  # type: ignore[union-attr]
        assert citation.act_id == "PROJECT"
        assert not citation.is_verified
    drawing = BOOK.rule("R-LAWN-DRAW-001").citation  # type: ignore[union-attr]
    assert drawing.act_id == "GOST_21_508_2020"
    assert drawing.is_verified
    assert "газоны наносят" in drawing.quote

    texts = {e.subject_id: e for e in explain(plan, BOOK).explanations}
    kept_text = texts[kept.lawn_id]
    assert kept_text.kind == "lawn"
    assert "сохраняемый или восстанавливаемый" in kept_text.text
    assert "R-LAWN-KEPT-001: параметр проекта" in kept_text.text
    assert "(цитата не сверена)" in kept_text.text
    assert "R-LAWN-DRAW-001: ГОСТ 21.508-2020, п. 10.4" in kept_text.text
    radius = f"{TREE_PIT_M:g}".replace(".", ",")
    assert f"деревьев 1 (круг радиусом {radius} м)" in kept_text.text
    new_text = texts[new.lawn_id].text
    assert "устраиваемый" in new_text
    assert "R-LAWN-NEW-001" in new_text
    assert "кустарников 1 (круг радиусом 0,5 м)" in new_text


def test_flowerbed_and_woodland_stay_out_and_are_reported() -> None:
    plan, _ = _lawns()

    warnings = _lawn_warnings(plan)
    assert any("цветники по чертежу" in w for w in warnings)
    assert plan.stats["lawn_small_parts"] == 0


def test_lawn_label_makes_soil_face_a_kept_lawn() -> None:
    plan, _ = _lawns(labels=(_label("ГАЗОН", 30, 26),))

    assert {lawn.kind for lawn in plan.lawns} == {LawnKind.KEPT}
    assert any(FACE_B.covers(lawn.geometry) for lawn in plan.lawns)


def test_small_parts_are_dropped_and_counted() -> None:
    plan, _ = _lawns(PlanParams(lawn_min_area_m2=550))

    assert [lawn.kind for lawn in plan.lawns] == [LawnKind.NEW]
    assert plan.stats["lawn_small_parts"] == 1
    pit = reserved_buffer(Point(0, 0), TREE_PIT_M).area
    assert plan.stats["lawn_small_m2"] == pytest.approx(LAWN_CONTOUR.area - pit, abs=0.1)


def test_kind_without_its_own_rule_is_not_issued() -> None:
    plan, _ = _lawns(PlanParams(disabled_rules=("R-LAWN-NEW-001",)))

    assert [lawn.kind for lawn in plan.lawns] == [LawnKind.KEPT]
    assert any("нет правила устраиваемого газона" in w for w in _lawn_warnings(plan))


def test_stage_is_switched_off_by_the_profile() -> None:
    lawned, _ = _lawns()
    features, labels, surface = _scene()

    plan = plan_lawns(
        lawned,
        features=features,
        labels=labels,
        surface=surface,
        rulebook=BOOK,
        params=PlanParams(lawns=False),
    )

    assert plan.lawns == ()
    assert _lawn_warnings(plan) == []


def test_recount_replaces_lawns_and_warnings() -> None:
    once, _ = _lawns()
    features, labels, surface = _scene()

    twice = plan_lawns(
        once, features=features, labels=labels, surface=surface, rulebook=BOOK, params=PlanParams()
    )

    assert [lawn.lawn_id for lawn in twice.lawns] == [lawn.lawn_id for lawn in once.lawns]
    assert _lawn_warnings(twice) == _lawn_warnings(once)


def test_no_work_boundary_or_soil_means_no_lawn() -> None:
    strict, _ = _lawns(boundary=False)
    assert strict.lawns == ()
    assert any("нет границы работ" in w for w in _lawn_warnings(strict))

    relaxed, _ = _lawns(PlanParams(require_work_boundary=False), boundary=False)
    assert [lawn.kind for lawn in relaxed.lawns] == [LawnKind.KEPT, LawnKind.NEW]

    features, labels, _ = _scene()
    bare = plan_lawns(
        PLAN, features=features, labels=labels, surface=None, rulebook=BOOK, params=PlanParams()
    )
    assert bare.lawns == ()
    assert any("нет грунта" in w for w in _lawn_warnings(bare))


@pytest.fixture(scope="module")
def street(tmp_path_factory: pytest.TempPathFactory) -> tuple[RunReport, tuple[Species, ...]]:
    work = tmp_path_factory.mktemp("lawns")
    source = work / "street.dxf"
    _street(source)
    container = build_container(Settings(config_dir=ROOT / "config", runs_dir=work / "runs"))
    params = container.profiles.load("strict", {"placement_solver": "greedy", "max_rejections": 50})
    report = container.use_case.execute(
        PlanRequest("lawns", source, work / "out", "strict", params)
    )
    return report, container.species.all()


def test_edit_recounts_lawn_around_the_new_plan(
    street: tuple[RunReport, tuple[Species, ...]],
) -> None:
    """Правка плана сдвигает посадочные места: газон пересчитывается по той же карте покрытий."""
    report, catalog = street
    assert report.context is not None
    before = report.plan
    assert before.lawns
    tree = next(
        p
        for p in before.placements
        if p.species.is_tree and 22 < p.y < 53 and 2 < p.x < 118  # яма целиком в газоне
    )

    edited = apply_edits(
        report.context, [Edit(EditKind.DELETE, placement_id=tree.placement_id)], catalog
    )

    gained = sum(g.area_m2 for g in edited.lawns) - sum(g.area_m2 for g in before.lawns)
    assert gained == pytest.approx(reserved_buffer(Point(0, 0), TREE_PIT_M).area, abs=0.01)
    assert _lawn_warnings(edited) == _lawn_warnings(before)
    texts = {e.subject_id for e in edited.explanations}
    assert {lawn.lawn_id for lawn in edited.lawns} <= texts
