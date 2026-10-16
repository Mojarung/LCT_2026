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
