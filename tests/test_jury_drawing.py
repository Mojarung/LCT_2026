"""Чертёж жюри 236287 (08.10.2026): проходит без JSON поверх профиля.

Файл заказчика в git не идёт (dataset/jury/), без него тест пропускается. Жюри остановилось на
ошибке единиц и не нашло, куда вписать drawing_unit; классы слоёв команда передавала руками.
"""

from __future__ import annotations

from pathlib import Path

import ezdxf
import pytest
from shapely.geometry import LineString

from green.domain.objects import Feature, ObjectClass, SourceRef
from green.infrastructure.cad.units import decide_units
from green.infrastructure.config.repositories import YamlLayerMapSource

ROOT = Path(__file__).resolve().parents[1]
JURY = ROOT / "dataset" / "jury" / "236287.dxf"
pytestmark = pytest.mark.skipif(not JURY.exists(), reason="чертёж жюри только локально")


def test_units_are_taken_from_the_geometry_with_a_note() -> None:
    decision = decide_units(ezdxf.readfile(JURY))
    assert decision.unit_m == 1.0
    assert decision.notes[0].startswith("Исправлено автоматически")


def test_layers_the_team_passed_by_hand_are_recognised() -> None:
    doc = ezdxf.readfile(JURY)
    layer_map = YamlLayerMapSource(ROOT / "config" / "layer_map.yaml").load()
    present = {e.dxf.layer for e in doc.modelspace()}
    by_hand = {
        "BOUND": ObjectClass.WORK_BOUNDARY,
        "DOROGA": ObjectClass.CURB,
        "DOM": ObjectClass.BUILDING,
        "ZABOR": ObjectClass.FENCE,
        "LAWN": ObjectClass.LAWN,
    }
    for layer, expected in by_hand.items():
        assert layer in present
        feature = Feature(SourceRef("f", "x", "1"), layer, LineString([(0, 0), (5, 0)]))
        assert layer_map.decide(feature)[0] is expected, layer
