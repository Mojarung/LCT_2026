"""DXF entity order must not change the species assigned beneath existing trees."""

from shapely.geometry import LineString, Point, box
from test_surface_uncertainty import CONFIG, RULES, feature

from green.application.params import PlanParams
from green.application.understory import fill_understory
from green.domain.objects import ObjectClass
from green.domain.planting import Plan
from green.infrastructure.config.repositories import YamlSpeciesCatalog


def test_reordering_existing_trees_keeps_understory_locations_and_species() -> None:
    features = [
        feature(ObjectClass.WORK_BOUNDARY, box(0, 0, 65, 30)),
        feature(ObjectClass.LAWN, box(0, 0, 65, 30)),
        feature(ObjectClass.UTILITY_WATER, LineString([(0, 1), (65, 1)])),
        *[feature(ObjectClass.EXISTING_TREE, Point(x, 15), str(x)) for x in (10, 30, 50)],
    ]
    catalog = YamlSpeciesCatalog(CONFIG / "species.yaml").all()

    def planted(objects: list) -> list:
        plan = fill_understory(
            Plan((), ()),
            features=objects,
            labels=[],
            rulebook=RULES,
            catalog=catalog,
            params=PlanParams(),
        )
        assert plan.placements
        return sorted((p.x, p.y, p.species.code, p.placement_id) for p in plan.placements)

    assert planted(features) == planted(list(reversed(features)))
