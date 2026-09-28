"""DXF для проектировщика: у посадки в атрибуте NPA - правило с актом и пунктом, на слое
GREEN_SCHEDULE - ведомость элементов озеленения (ГОСТ 21.508-2020, форма 9)."""

from __future__ import annotations

from pathlib import Path

import ezdxf

from green.domain.norms import PlantingType
from green.domain.objects import ObjectClass
from green.domain.planting import (
    CheckOutcome,
    LifeForm,
    Placement,
    Plan,
    RuleCheck,
    Species,
    Verdict,
)
from green.infrastructure.cad.export_validation import check_written_plan
from green.infrastructure.cad.writer import EzdxfPlanWriter
from green.infrastructure.config.repositories import YamlRuleBookSource

ROOT = Path(__file__).resolve().parents[1]
BOOK = YamlRuleBookSource(ROOT / "config" / "acts.yaml", ROOT / "config" / "rules.yaml").load()
LIME = Species(
    "tilia_cordata", "Липа мелколистная", "Tilia cordata", 5, life_form=LifeForm.TREE_LARGE
)
SPIREA = Species(
    "spiraea_vanhouttei",
    "Спирея Вангутта",
    "Spiraea vanhouttei",
    1.5,
    life_form=LifeForm.SHRUB_MEDIUM,
)


def _placement(number: int, species: Species, x: float) -> Placement:
    kind = PlantingType.SHRUB if species.is_shrub else PlantingType.TREE
    check = RuleCheck(
        "R-SEWER-TREE-001",
        CheckOutcome.PASS,
        threshold_m=1.5,
        measured_m=3.0,
        object_class=ObjectClass.UTILITY_SEWER,
    )
    return Placement(f"p{number}", number, kind, species, x, 10.0, Verdict.ALLOWED, (check,))


def _written(tmp_path: Path) -> tuple[Path, Plan]:
    source = tmp_path / "source.dxf"
    doc = ezdxf.new("R2018")
    doc.modelspace().add_line((0, 0), (100, 0))
    doc.saveas(source)
    plan = Plan(
        (_placement(1, LIME, 10.0), _placement(2, LIME, 16.0), _placement(3, SPIREA, 20.0)), ()
    )
    target = tmp_path / "result.dxf"
    EzdxfPlanWriter(text_font="DejaVuSans").write(source, plan, BOOK, target)
    return target, plan


def test_npa_attribute_names_the_act_and_clause(tmp_path: Path) -> None:
    target, _ = _written(tmp_path)
    insert = ezdxf.readfile(target).modelspace().query("INSERT[layer=='GREEN_TREES']").first
    npa = next(a.dxf.text for a in insert.attribs if a.dxf.tag == "NPA")
    assert "R-SEWER-TREE-001" in npa
    assert "СП 42.13330" in npa
    assert "табл. 9.1" in npa


def test_schedule_of_planting_elements_is_drawn_on_its_layer(tmp_path: Path) -> None:
    target, plan = _written(tmp_path)
    doc = ezdxf.readfile(target)
    texts = [t.dxf.text for t in doc.modelspace().query("TEXT[layer=='GREEN_SCHEDULE']")]
    assert "Ведомость элементов озеленения" in texts
    assert "Липа мелколистная" in texts
    assert "Спирея Вангутта" in texts
    assert "2" in texts  # две липы
    assert doc.modelspace().query("LINE[layer=='GREEN_SCHEDULE']")
    assert check_written_plan(target, plan, unit_m=1.0).ok
