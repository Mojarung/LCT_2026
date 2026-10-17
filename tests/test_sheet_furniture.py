"""Оформление листа на слое 0 внутри листа съёмки: легенда, штамп, расчленённый текст.

Листы ИГДИ «Мосгеотреста» вставлены в чертёж блоком внешней ссылки. Слой 0 внутри блока
наследует слой вставки (например, «!ВН_ССЫЛ_ИТП»), которого нет в словаре слоёв, и раньше
всё это уходило в «линию без смысла» по одной геометрии: на Камчатской 4 621 объект, на
3-й Парковой - десятки тысяч, и каждый требовал проверки на странице уточнения. Перепись
17-18.10.2026: это условные обозначения, штампы листов и текст, разобранный на штрихи.
"""

from __future__ import annotations

from pathlib import Path

from shapely.geometry import LineString

from green.application.classification import classify_scene
from green.application.params import PlanParams
from green.domain.objects import Feature, ObjectClass, Scene, SourceRef, TextLabel
from green.infrastructure.config.repositories import YamlLayerMapSource

ROOT = Path(__file__).resolve().parents[1]
LAYER = "!ВН_ССЫЛ_ИТП"  # слой вставки листа; в словаре слоёв его нет
BLOCK = "Гео_Камчатская улица"
RULES = YamlLayerMapSource(ROOT / "config/layer_map.yaml").load()


def _line(handle: str, coords: list[tuple[float, float]], layer: str = LAYER) -> Feature:
    return Feature(SourceRef("f", "x", handle), layer, LineString(coords), block=BLOCK)


def _label(handle: str, x: float, y: float, text: str) -> TextLabel:
    return TextLabel(SourceRef("f", "x", handle), LAYER, x, y, text, block=BLOCK)


def _legend() -> tuple[list[Feature], list[TextLabel]]:
    """Шапка «Условные обозначения», под ней строки: образец линии и подпись справа."""
    features, labels = [], [_label("h", 0, 20, "Условные обозначения")]
    for row in range(6):
        y = 16 - 3.7 * row
        features.append(_line(f"s{row}", [(0, y), (8, y)]))
        labels.append(_label(f"t{row}", 10, y, f"границы зоны {row}"))
    return features, labels


def _classified(features: list[Feature], labels: list[TextLabel], **params: object) -> dict:
    scene = Scene("s.dxf", "0" * 64, "AC1032", tuple(features), tuple(labels))
    done, _ = classify_scene(scene, RULES, PlanParams(**params))
    return {f.ref.handle: f for f in done.features}


def test_legend_rows_under_the_header_are_sheet_furniture() -> None:
    features, labels = _legend()
    result = _classified(features, labels)
    for row in range(6):
        feature = result[f"s{row}"]
        assert feature.object_class is ObjectClass.IGNORE
        assert feature.classification is not None
        assert feature.classification.method.startswith("sheet_furniture:")


def test_title_block_grid_is_sheet_furniture() -> None:
    grid = [_line(f"g{i}", [(200, 100 + 2 * i), (260, 100 + 2 * i)]) for i in range(6)]
    grid += [_line(f"v{i}", [(200 + 15 * i, 100), (200 + 15 * i, 110)]) for i in range(5)]
    stamp = [
        _label("a", 202, 101, "Изм."),
        _label("b", 217, 101, "Подпись"),
        _label("c", 250, 109, "Лист"),
    ]
    result = _classified(grid, stamp)
    assert all(result[f.ref.handle].object_class is ObjectClass.IGNORE for f in grid)


def test_exploded_text_strokes_are_sheet_furniture() -> None:
    """Подпись, разобранная на штрихи по 0,1-0,3 м, без слов-якорей рядом."""
    strokes = [
        _line(f"k{i}", [(500 + 0.35 * i, 50), (500 + 0.35 * i + 0.2, 50.25)]) for i in range(40)
    ]
    result = _classified(strokes, [])
    assert all(result[f.ref.handle].object_class is ObjectClass.IGNORE for f in strokes)
    assert result["k0"].classification.method == "sheet_furniture:text_strokes"


def test_strokes_stay_unknown_without_geometry_assumptions() -> None:
    strokes = [
        _line(f"k{i}", [(500 + 0.35 * i, 50), (500 + 0.35 * i + 0.2, 50.25)]) for i in range(40)
    ]
    result = _classified(strokes, [], assume_unknown_geometry=False)
    assert result["k0"].object_class is ObjectClass.UNKNOWN


def test_unknown_line_far_from_any_sheet_text_stays_geometry_only() -> None:
    features, labels = _legend()
    far = _line("far", [(400, 300), (440, 330), (470, 310)])
    result = _classified([*features, far], labels)
    assert result["far"].object_class is ObjectClass.CONTOUR
    assert result["far"].classification.method.startswith("assumed_geometry")


def test_mapped_layer_next_to_the_legend_keeps_its_class() -> None:
    features, labels = _legend()
    cable = _line("cab", [(0, 18), (8, 18)], layer="Кабель электрический")
    result = _classified([*features, cable], labels)
    assert result["cab"].object_class is ObjectClass.UTILITY_POWER


def test_review_profile_leaves_the_legend_for_the_reviewer() -> None:
    features, labels = _legend()
    result = _classified(features, labels, infer_unknown=False)
    assert result["s0"].object_class is ObjectClass.UNKNOWN


def test_non_plot_layers_are_never_objects_whatever_the_block() -> None:
    """Defpoints и «Не печатать» AutoCAD не выводит на печать: это построения, а не объекты.
    Аудит Берзарина 16.10: линии Defpoints в блоке борта считались бортом по имени блока."""
    cases = [
        ("Defpoints", "ПП_Борт_БР100"),
        ("DEFPOINTS", "Бортовой камень"),
        ("Не печатать", "Газон"),
    ]
    features = [
        Feature(SourceRef("f", "x", str(i)), layer, LineString([(0, 0), (5, 0)]), block=block)
        for i, (layer, block) in enumerate(cases)
    ]
    result = _classified(features, [])
    for i in range(len(cases)):
        assert result[str(i)].object_class is ObjectClass.IGNORE, cases[i]
