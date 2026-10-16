"""Классы объектов из словарей конфигурации, которые решают, какая норма применяется.

Аудит Берзарина 16.10.2026 (docs/research/jury-audit-2026-10-16): дорожный знак получал
правило осветительной опоры (4 м), лестница и стела - правило подпорной стенки (3 м).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from green.domain.objects import ObjectClass
from green.infrastructure.config.repositories import YamlLayerMapSource

ROOT = Path(__file__).resolve().parents[1]
LAYER_MAP = YamlLayerMapSource(ROOT / "config/layer_map.yaml").load()


def test_road_sign_is_an_obstacle_not_a_light_pole() -> None:
    entry = LAYER_MAP.symbols.get("DORZN1")
    assert entry is not None
    assert entry.object_class is ObjectClass.OBSTACLE


@pytest.mark.parametrize("name", ["Лестница", "Ступени", "Пандус", "Стела навигации"])
def test_stairs_and_stelae_are_obstacles_not_retaining_walls(name: str) -> None:
    found = LAYER_MAP.vocabulary.infer(None, name)
    assert found is not None
    assert found.object_class is ObjectClass.OBSTACLE


@pytest.mark.parametrize("name", ["Подпорная стенка", "Парапет"])
def test_retaining_walls_keep_the_retaining_wall_rule(name: str) -> None:
    found = LAYER_MAP.vocabulary.infer(None, name)
    assert found is not None
    assert found.object_class is ObjectClass.STRUCTURE


def _feature(layer: str, block: str | None) -> object:
    from shapely.geometry import LineString

    from green.domain.objects import Feature, SourceRef

    return Feature(SourceRef("f", "x", "1"), layer, LineString([(0, 0), (5, 0)]), block=block)


@pytest.mark.parametrize(
    ("layer", "block"),
    [
        # Чекпоинт 16.10.2026, п. 2, и перепись прогонов 19 улиц: линии этих листов на слое 0
        # выводились «контуром по геометрии» (39 тыс. объектов) и делили газон на части.
        ("0_геоподоснова", "output[19-22]_3_ДЖКХ-25_01840kl"),  # красные линии, Берзарина
        ("0", "output[1-4]_edge001"),  # лист линий градостроительного регулирования
        ("0", "output[1-4]_edge001$0$RL 2.8.3"),  # знак линии регулирования
        ("0", "output[5-7]_edge005$0$RL 3.13"),
    ],
)
def test_red_lines_and_regulation_lines_are_not_surfaces(layer: str, block: str) -> None:
    found, evidence = LAYER_MAP.decide(_feature(layer, block))  # type: ignore[arg-type]
    assert found is ObjectClass.IGNORE
    assert evidence.method == "name_rule"


def test_topographic_sheet_block_is_not_caught_by_the_red_line_rule() -> None:
    """Негативный контроль: лист топоплана (tp) правилом красных линий не снимается."""
    _, evidence = LAYER_MAP.decide(_feature("0", "output[1-12]_3_ДЖКХ-24_03233tp"))  # type: ignore[arg-type]
    reasons = [LAYER_MAP.rules[i].reason for i in evidence.matched_rules]
    assert not any("красн" in reason for reason in reasons)
