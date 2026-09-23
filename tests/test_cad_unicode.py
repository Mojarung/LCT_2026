"""Legacy code pages can represent Cyrillic via DXF CIF escapes, also in names."""

from __future__ import annotations

from pathlib import Path

import ezdxf
import pytest

from green.application.classification import classify_scene
from green.domain.norms import PlantingType, RuleBook
from green.domain.objects import ObjectClass
from green.domain.planting import Placement, Plan, Species, Verdict
from green.infrastructure.cad.export_validation import check_written_plan
from green.infrastructure.cad.reader import EzdxfSceneReader
from green.infrastructure.cad.writer import EzdxfPlanWriter
from green.infrastructure.config.repositories import YamlLayerMapSource


@pytest.mark.parametrize("version", ["R2000", "R2004", "R2018"])
@pytest.mark.parametrize("encoding", ["cp1251", "cp1252"])
def test_cyrillic_names_labels_and_nested_context_are_read_without_source_changes(
    tmp_path: Path, version: str, encoding: str
) -> None:
    doc = ezdxf.new(version)
    doc.units = 6
    doc.encoding = encoding
    doc.layers.new("Газон")
    block = doc.blocks.new("Пояснительные")
    block.add_lwpolyline(
        [(0, 0), (20, 0), (20, 20), (0, 20)], close=True, dxfattribs={"layer": "Газон"}
    )
    block.add_text("ГАЗОН", dxfattribs={"insert": (5, 5)})
    block.add_mtext("ГРУНТ", dxfattribs={"insert": (7, 7)})
    instance = doc.modelspace().add_blockref("Пояснительные", (100, 200))
    instance.add_attrib("MATERIAL", "ЦВЕТНИК", (102, 203))
    path = tmp_path / "unicode.dxf"
    doc.saveas(path)
    before = path.read_bytes()
    scene = EzdxfSceneReader().read(path)
    assert scene.features[0].layer == "Газон"
    assert scene.features[0].block == "Пояснительные"
    assert {t.text for t in scene.labels} == {"ГАЗОН", "ГРУНТ", "ЦВЕТНИК"}
    assert all(t.block_chain == ("Пояснительные",) for t in scene.labels)
    rules = YamlLayerMapSource(Path(__file__).resolve().parents[1] / "config/layer_map.yaml").load()
    classified, _ = classify_scene(scene, rules)
    assert classified.features[0].object_class is ObjectClass.LAWN
    assert path.read_bytes() == before


@pytest.mark.parametrize("version", ["R2000", "R2004", "R2018"])
@pytest.mark.parametrize("encoding", ["cp1251", "cp1252"])
def test_export_certificate_compares_decoded_species_and_still_detects_mutation(
    tmp_path: Path, version: str, encoding: str
) -> None:
    doc = ezdxf.new(version)
    doc.units = 6
    doc.encoding = encoding
    source = tmp_path / "source.dxf"
    doc.saveas(source)
    species = Species("tilia", "Липа мелколистная", "Tilia cordata", 4)
    plan = Plan((Placement("p-1", 1, PlantingType.TREE, species, 10, 20, Verdict.ALLOWED, ()),), ())
    result = tmp_path / "result.dxf"
    EzdxfPlanWriter(text_font="DejaVuSans").write(source, plan, RuleBook({}, (), "test"), result)
    assert check_written_plan(result, plan, unit_m=1).ok
    written = ezdxf.readfile(result)
    tree = written.modelspace().query("INSERT").first
    assert tree is not None
    species_attribute = tree.get_attrib("SPECIES")
    assert species_attribute is not None
    species_attribute.dxf.text = "Ива белая"
    written.saveas(result)
    assert not check_written_plan(result, plan, unit_m=1).ok
