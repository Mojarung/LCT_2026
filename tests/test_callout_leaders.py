"""Выноска к сети на слое сети - оформление, а не трасса (Ярослав и Булат, 17.10.2026).

На слоях сетей подоснов стрелка-выноска от подписи («2тр.», «152.05лот.», «гидрант») к трассе
лежит тем же слоем. Распознавание составных выносок (application/callouts.py) снимало сразу
только подпись кабельного колодца, остальное оставалось сетью «на проверку»: на Камчатской
1 108 выносок, вдоль каждой - отступ кабеля, и посадка отвергается там, где кабеля нет.

Выноска снимается без проверки человеком, когда рисунок однозначен: острие касается только
своих двух штрихов (не продолжение сети), хвост свободен или кончается полкой под подписью,
стержень не лежит поверх другой линии слоя (стрелка направления течения на трубе) и не
длиннее 40 м. Иначе - прежняя проверка.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from shapely.geometry import LineString

from green.application.callouts import recognise_callouts
from green.application.classification import classification_report, classify_scene
from green.domain.objects import Feature, ObjectClass, Scene, SourceRef, TextLabel
from green.infrastructure.config.repositories import YamlLayerMapSource

ROOT = Path(__file__).resolve().parents[1]
LAYERS = YamlLayerMapSource(ROOT / "config/layer_map.yaml").load()
LAYER = "Кабель связи"


def _line(handle: str, coords: list[tuple[float, float]]) -> Feature:
    return Feature(SourceRef("12345678", "00000000", handle), LAYER, LineString(coords))


def _scene(*extra: Feature, text: str = "152.05лот.") -> Scene:
    """Стержень от подписи (0, 2) к острию (10, 0) на трассе x = 10.05, два штриха стрелки."""
    trace = _line("trace", [(10.05, -6), (10.05, 6)])
    return Scene(
        "leader.dxf",
        "a" * 64,
        "AC1032",
        (
            _line("shaft", [(10, 0), (8, 2), (0, 2)]),
            _line("left", [(10, 0), (9.2, 0.3)]),
            _line("right", [(10, 0), (9.7, 0.8)]),
            trace,
            *extra,
        ),
        (TextLabel(SourceRef("12345678", "00000000", "t"), LAYER, 0, 2.5, text),),
    )


def _classes(scene: Scene) -> dict[str, Feature]:
    done, _ = classify_scene(scene, LAYERS)
    return {f.ref.handle: f for f in done.features}


def test_leader_to_a_trace_is_annotation_and_the_trace_stays() -> None:
    result = _classes(_scene())
    for part in ("shaft", "left", "right"):
        assert result[part].object_class is ObjectClass.IGNORE
        assert result[part].classification.method.startswith("callout_leader:")
    assert result["trace"].object_class is ObjectClass.UTILITY_TELECOM


def test_leader_is_not_left_for_review() -> None:
    done, _ = classify_scene(_scene(), LAYERS)
    assert classification_report(done, LAYERS).review_required_features == 0


def test_shelf_under_the_label_is_part_of_the_leader() -> None:
    shelf = _line("shelf", [(0, 2), (-3, 2)])
    result = _classes(_scene(shelf))
    assert result["shaft"].object_class is ObjectClass.IGNORE
    assert result["shelf"].object_class is ObjectClass.IGNORE


def test_flow_arrow_lying_on_a_pipe_stays_a_network() -> None:
    pipe = _line("pipe", [(-5, 2.02), (8.5, 2.02)])
    result = _classes(_scene(pipe))
    assert result["shaft"].object_class is ObjectClass.UTILITY_TELECOM
    assert result["pipe"].object_class is ObjectClass.UTILITY_TELECOM


def test_tail_joined_to_another_network_line_stays_for_review() -> None:
    branch = _line("branch", [(0, 2), (-4, 8)])
    onward = _line("onward", [(-4, 8), (-20, 8)])
    result = _classes(_scene(branch, onward))
    assert result["shaft"].object_class is ObjectClass.UTILITY_TELECOM
    assert result["shaft"].classification.method.startswith("callout_candidate:")


def test_tip_on_a_trace_vertex_is_still_a_leader() -> None:
    """Острие попало в вершину трассы: трасса разбита на два отрезка в этой точке."""
    scene = _scene()
    up = _line("up", [(10, 0), (10.05, 6)])
    down = _line("down", [(10, 0), (10.05, -6)])
    features = tuple(f for f in scene.features if f.ref.handle != "trace")
    result = _classes(replace(scene, features=(*features, up, down)))
    assert result["shaft"].object_class is ObjectClass.IGNORE
    assert result["up"].object_class is ObjectClass.UTILITY_TELECOM
    assert result["down"].object_class is ObjectClass.UTILITY_TELECOM


def test_continuation_at_the_tip_stays_for_review() -> None:
    scene = _scene()
    cable = _line("cable", [(10, 0), (15, -2)])
    result = _classes(replace(scene, features=(*scene.features, cable)))
    assert result["shaft"].object_class is ObjectClass.UTILITY_TELECOM


def test_overlong_shaft_is_not_taken_for_a_leader() -> None:
    long = Scene(
        "leader.dxf",
        "a" * 64,
        "AC1032",
        (
            _line("shaft", [(10, 0), (8, 2), (-60, 2)]),
            _line("left", [(10, 0), (9.2, 0.3)]),
            _line("right", [(10, 0), (9.7, 0.8)]),
        ),
        (TextLabel(SourceRef("12345678", "00000000", "t"), LAYER, -60, 2.5, "2тр."),),
    )
    assert not any(c.leader for c in recognise_callouts(long))


def test_arrow_at_a_bend_of_the_trace_keeps_the_segment_for_review() -> None:
    """Ревью 18.10.2026: стрелка направления на изломе кабеля (продолжение уходит под 60°),
    у хвоста - подпись колодца. Стержень здесь - сам отрезок кабеля: снять его без проверки
    значит убрать отступ кабеля под посадками."""
    pipe = _line("pipe_a", [(0, 0), (20, 0)])
    turn = _line("pipe_b", [(20, 0), (27.5, 12.99)])
    wings = (_line("wl", [(20, 0), (19.2, 0.35)]), _line("wr", [(20, 0), (19.2, -0.35)]))
    label = TextLabel(SourceRef("12345678", "00000000", "t"), LAYER, -1.0, 1.0, "К-12")
    scene = Scene("bend.dxf", "b" * 64, "AC1032", (pipe, turn, *wings), (label,))
    result = _classes(scene)
    assert result["pipe_a"].object_class is not ObjectClass.IGNORE
    assert not any(c.leader for c in recognise_callouts(scene))


def test_leader_landing_where_the_trace_passes_through_is_still_annotation() -> None:
    """Острие на вершине трассы, которая проходит насквозь (два отрезка по одной прямой), -
    выноска к сети, как и острие посреди отрезка."""
    upper = _line("trace_up", [(10, 0), (10, 6)])
    lower = _line("trace_down", [(10, 0), (10, -6)])
    scene = Scene(
        "through.dxf",
        "c" * 64,
        "AC1032",
        (
            _line("shaft", [(10, 0), (8, 2), (0, 2)]),
            _line("left", [(10, 0), (9.2, 0.3)]),
            _line("right", [(10, 0), (9.7, 0.8)]),
            upper,
            lower,
        ),
        (TextLabel(SourceRef("12345678", "00000000", "t"), LAYER, 0, 2.5, "152.05лот."),),
    )
    result = _classes(scene)
    assert result["shaft"].object_class is ObjectClass.IGNORE
    assert result["trace_up"].object_class is not ObjectClass.IGNORE
