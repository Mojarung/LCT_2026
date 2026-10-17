"""Unknown spatial entities require review when geometry assumptions are disabled."""

from pathlib import Path

import ezdxf

from green.application.classification import classification_report, classify_scene
from green.application.params import PlanParams
from green.domain.objects import ObjectClass
from green.infrastructure.cad.reader import EzdxfSceneReader
from green.infrastructure.config.repositories import YamlLayerMapSource

ROOT = Path(__file__).resolve().parents[1]


def test_unidentified_line_is_not_assumed_harmless(tmp_path: Path) -> None:
    source = tmp_path / "unknown.dxf"
    document = ezdxf.new("R2018")
    document.units = 6
    document.layers.new("Слой-901")
    document.modelspace().add_line((0, 0), (10, 0), dxfattribs={"layer": "Слой-901"})
    document.saveas(source)

    scene = EzdxfSceneReader().read(source)
    rules = YamlLayerMapSource(ROOT / "config/layer_map.yaml").load()
    # По умолчанию линия принимается за контур: класс есть, но назначение только по геометрии
    # остаётся на проверку человеку (e755a87: ready учитывает и такие объекты).
    default = classification_report(classify_scene(scene, rules, PlanParams())[0], rules)
    assert default.unresolved_features == 0
    assert default.review_required_features == 1
    reviewed_scene, _ = classify_scene(scene, rules, PlanParams(assume_unknown_geometry=False))
    report = classification_report(reviewed_scene, rules)
    assert report.unresolved_features == 1
    assert not report.ready
    assert report.unresolved_features == 1
    assert reviewed_scene.features[0].classification.method == "unmatched"

    resolved, _ = classify_scene(
        scene,
        rules,
        PlanParams(assume_unknown_geometry=False, layer_classes={"Слой-901": "utility.water"}),
    )
    assert resolved.features[0].object_class is ObjectClass.UTILITY_WATER
    assert classification_report(resolved, rules).ready
