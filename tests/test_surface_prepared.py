"""Карта покрытий из pickle (контекст правки после перезапуска): подготовка геометрий
shapely при сохранении теряется и восстанавливается при первом обращении к материалу."""

from __future__ import annotations

import pickle

import numpy as np
import shapely
from shapely.geometry import box

from green.application.surfaces import Material, SurfaceMap


def test_material_prepares_areas_lost_by_pickle() -> None:
    surface = SurfaceMap(
        grid=np.zeros((1, 1), dtype=np.int8),
        origin=(0.0, 0.0),
        cell=1.0,
        seeds_paved=1,
        seeds_soil=1,
        soil_area=box(0, 0, 10, 10),
        paved_area=box(20, 0, 30, 10),
    )
    back = pickle.loads(pickle.dumps(surface))
    assert not shapely.is_prepared(back.soil_area)
    found = back.material(shapely.points([(5.0, 5.0), (25.0, 5.0)]))
    assert found.tolist() == [int(Material.SOIL), int(Material.PAVED)]
    assert shapely.is_prepared(back.soil_area)
    assert shapely.is_prepared(back.paved_area)
