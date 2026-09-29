"""DXF для CAD: у посадки видна позиция ведомости - обычный TEXT на GREEN_LABELS там, где атрибут
POS, а сам POS, номер, вид и нормы скрыты; ведомость стоит справа от габарита всего плана,
легенда правил - справа от ведомости, в единицах чертежа.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import TYPE_CHECKING

import ezdxf
import pytest
from ezdxf.addons.drawing import Frontend, RenderContext
from ezdxf.addons.drawing.recorder import Recorder
from shapely.geometry import box

from green.domain.norms import LawnKind, PlantingType
from green.domain.objects import ObjectClass
from green.domain.planting import (
    CheckOutcome,
    Lawn,
    LifeForm,
    Placement,
    Plan,
    Rejection,
    RuleCheck,
    Species,
    Verdict,
    Zone,
)
from green.infrastructure.cad.export_validation import check_written_plan
from green.infrastructure.cad.writer import LAYER_LABELS, LAYER_SCHEDULE, EzdxfPlanWriter
from green.infrastructure.config.repositories import YamlRuleBookSource

if TYPE_CHECKING:
    from ezdxf.document import Drawing
    from ezdxf.entities import Attrib, Insert, MText, Text

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
LABEL_HEIGHT_M = 0.5
# План вдали от начала координат: легенда или ведомость в точке (0, 0) не сойдёт за «правее плана».
X0, Y0 = 1000.0, 500.0
MM = 0.001


def _check(outcome: CheckOutcome = CheckOutcome.PASS) -> RuleCheck:
    return RuleCheck(
        "R-SEWER-TREE-001",
        outcome,
        threshold_m=1.5,
        measured_m=3.0 if outcome is CheckOutcome.PASS else 1.0,
        object_class=ObjectClass.UTILITY_SEWER,
    )


def _placement(number: int, species: Species, x: float, y: float = Y0) -> Placement:
    kind = PlantingType.SHRUB if species.is_shrub else PlantingType.TREE
    return Placement(f"p{number}", number, kind, species, x, y, Verdict.ALLOWED, (_check(),))


def _rejection(number: int, x: float, y: float = Y0) -> Rejection:
    return Rejection(
        f"r{number}",
        number,
        PlantingType.TREE,
        x,
        y,
        Verdict.FORBIDDEN,
        (_check(CheckOutcome.FAIL),),
    )


def _lawn(minx: float, maxx: float) -> Lawn:
    return Lawn("lawn-1", 1, LawnKind.KEPT, box(minx, Y0 - 5, maxx, Y0 + 5), ("R-SEWER-TREE-001",))


def _mixed_plan() -> Plan:
    """Две липы и спирея: позиция ведомости не совпадает со сквозным номером у 2 из 3 посадок."""
    return Plan(
        (
            _placement(1, LIME, X0),
            _placement(2, LIME, X0 + 6),
            _placement(3, SPIREA, X0 + 10),
        ),
        (),
    )


def _write(tmp_path: Path, plan: Plan, *, unit_m: float = 1.0) -> Path:
    source = tmp_path / "source.dxf"
    if not source.exists():
        doc = ezdxf.new("R2018")
        doc.modelspace().add_line((0, 0), (100, 0))
        doc.saveas(source)
    target = tmp_path / f"result-{unit_m}.dxf"
    EzdxfPlanWriter(text_font="DejaVuSans", label_height_m=LABEL_HEIGHT_M).write(
        source, plan, BOOK, target, unit_m=unit_m
    )
    return target


def _plantings(doc: Drawing) -> list[Insert]:
    return [
        e
        for e in doc.modelspace().query("INSERT")
        if e.dxf.name.startswith(("GREEN_TREE_", "GREEN_SHRUB_"))
    ]


def _attrs(insert: Insert) -> dict[str, Attrib]:
    return {a.dxf.tag: a for a in insert.attribs}


def _attr(insert: Insert, tag: str) -> Attrib:
    attrib = _attrs(insert).get(tag)
    assert attrib is not None, f"у вставки нет атрибута {tag}"
    return attrib


def _identity(entity: Insert | Text) -> str:
    """Идентификатор посадки из XDATA LCT_GREEN: у вставки и у подписи её позиции."""
    if not entity.has_xdata("LCT_GREEN"):
        return ""
    strings = [tag.value for tag in entity.get_xdata("LCT_GREEN") if tag.code == 1000]
    return strings[0] if strings else ""


def _position_labels(doc: Drawing) -> list[Text]:
    return list(doc.modelspace().query(f"TEXT[layer=='{LAYER_LABELS}']"))


def _plan_right_edge_m(plan: Plan) -> float:
    """Правый край всего, что план рисует, в метрах: кроны посадок, отказы, зоны, газоны."""
    edges = [p.x + p.species.crown_diameter_m / 2 for p in plan.placements]
    edges += [r.x for r in plan.rejections]
    edges += [item.geometry.bounds[2] for item in (*plan.zones, *plan.lawns)]
    return max(edges)


def _schedule_span(doc: Drawing) -> tuple[float, float]:
    """Левый и правый край ведомости: подписи и линии таблицы на её слое."""
    msp = doc.modelspace()
    xs = [t.dxf.insert.x for t in msp.query(f"TEXT[layer=='{LAYER_SCHEDULE}']")]
    for line in msp.query(f"LINE[layer=='{LAYER_SCHEDULE}']"):
        xs += [line.dxf.start.x, line.dxf.end.x]
    assert xs, "ведомость не нарисована"
    return min(xs), max(xs)


def _legend(doc: Drawing) -> MText:
    legends = list(doc.modelspace().query(f"MTEXT[layer=='{LAYER_LABELS}']"))
    assert len(legends) == 1, "легенда правил - один MTEXT"
    return legends[0]


def _legend_frame(legend: MText) -> tuple[float, float, float, float]:
    return (
        legend.dxf.insert.x,
        legend.dxf.insert.y,
        legend.dxf.get("width") or 0.0,
        legend.dxf.char_height,
    )


# --- позиция ведомости у посадки -------------------------------------------------------------


def test_planting_shows_schedule_position_not_running_number(tmp_path: Path) -> None:
    doc = ezdxf.readfile(_write(tmp_path, _mixed_plan()))
    inserts = _plantings(doc)
    assert len(inserts) == 3
    # Ведомость: раздел деревьев раньше кустарников - липа поз. 1, спирея поз. 2.
    shown = {_attr(i, "NUM").dxf.text: _attrs(i).get("POS") for i in inserts}
    shown = {num: pos.dxf.text if pos else None for num, pos in shown.items()}
    assert shown == {"1": "1", "2": "1", "3": "2"}


def test_schedule_position_attribute_stays_but_is_hidden(tmp_path: Path) -> None:
    # Видимый атрибут рядом с видимым текстом nanoCAD и AutoCAD нарисовали бы дважды.
    doc = ezdxf.readfile(_write(tmp_path, _mixed_plan()))
    for insert in _plantings(doc):
        position = _attr(insert, "POS")
        assert position.is_invisible
        assert math.isclose(position.dxf.height, LABEL_HEIGHT_M)
        assert position.dxf.layer == LAYER_LABELS


def test_position_attribute_is_hidden_even_if_source_block_shows_it(tmp_path: Path) -> None:
    # Исходником подали прежний result.dxf: блок вида уже есть, и POS в нём видимый.
    source = tmp_path / "source.dxf"
    doc = ezdxf.new("R2018")
    block = doc.blocks.new("GREEN_TREE_TILIA_CORDATA")
    block.add_circle((0, 0), radius=LIME.crown_diameter_m / 2)
    block.add_attdef("POS", (0.4, 0.4), dxfattribs={"height": LABEL_HEIGHT_M})
    doc.saveas(source)
    written = ezdxf.readfile(_write(tmp_path, _mixed_plan()))
    limes = [i for i in _plantings(written) if i.dxf.name == "GREEN_TREE_TILIA_CORDATA"]
    assert len(limes) == 2
    for insert in limes:
        assert _attr(insert, "POS").is_invisible


def test_schedule_position_is_plain_text_where_the_attribute_is(tmp_path: Path) -> None:
    # LibreCAD атрибуты вставок не рисует, обычный TEXT - рисует: номер виден в любом просмотрщике.
    doc = ezdxf.readfile(_write(tmp_path, _mixed_plan()))
    labels = _position_labels(doc)
    assert sorted(label.dxf.text for label in labels) == ["1", "1", "2"]
    by_planting = {_identity(label): label for label in labels}
    for insert in _plantings(doc):
        label = by_planting.get(_identity(insert))
        assert label is not None, f"у посадки {_identity(insert)} нет подписи позиции"
        position = _attr(insert, "POS")
        assert label.dxf.text == position.dxf.text
        assert label.dxf.insert.isclose(position.dxf.insert, abs_tol=1e-9)
        assert math.isclose(label.dxf.height, position.dxf.height)
        assert label.dxf.style == "GREEN_TEXT"


def test_position_text_is_in_drawing_units_for_millimetre_drawing(tmp_path: Path) -> None:
    plan = _mixed_plan()
    doc = ezdxf.readfile(_write(tmp_path, plan, unit_m=MM))
    points = {p.placement_id: (p.x / MM, p.y / MM) for p in plan.placements}
    labels = _position_labels(doc)
    assert len(labels) == len(plan.placements)
    for label in labels:
        x, y = points[_identity(label)]
        assert math.isclose(label.dxf.height, LABEL_HEIGHT_M / MM, rel_tol=1e-9)
        # Подпись справа сверху от точки посадки, дальше 0,1 м и ближе 1 м - в миллиметрах чертежа.
        assert 0.1 / MM < label.dxf.insert.x - x < 1 / MM
        assert 0.1 / MM < label.dxf.insert.y - y < 1 / MM


def test_number_species_and_norms_stay_but_are_hidden(tmp_path: Path) -> None:
    plan = _mixed_plan()
    doc = ezdxf.readfile(_write(tmp_path, plan))
    names = {str(p.number): p.species.name_ru for p in plan.placements}
    for insert in _plantings(doc):
        number, species, norms = (_attr(insert, tag) for tag in ("NUM", "SPECIES", "NPA"))
        assert number.is_invisible
        assert species.is_invisible
        assert norms.is_invisible
        assert species.dxf.text == names[number.dxf.text]
        assert "R-SEWER-TREE-001" in norms.dxf.text


# --- ведомость и легенда за габаритом плана ----------------------------------------------------


@pytest.mark.parametrize("rightmost", ["placement", "rejection", "zone", "lawn"])
def test_schedule_and_legend_stand_right_of_whole_plan(tmp_path: Path, rightmost: str) -> None:
    placements = [_placement(1, LIME, X0)]
    rejections, zones, lawns = [], [], []
    far = X0 + 60  # правее всех посадок больше, чем на прежний отступ ведомости
    if rightmost == "placement":
        placements.append(_placement(2, SPIREA, far))
    elif rightmost == "rejection":
        rejections.append(_rejection(1, far))
    elif rightmost == "zone":
        zones.append(Zone(Verdict.ALLOWED, box(X0 + 20, Y0 - 5, far, Y0 + 5)))
    else:
        lawns.append(_lawn(X0 + 20, far))
    plan = Plan(tuple(placements), tuple(rejections), zones=tuple(zones), lawns=tuple(lawns))
    doc = ezdxf.readfile(_write(tmp_path, plan))
    left, right = _schedule_span(doc)
    legend = _legend(doc)
    assert left > _plan_right_edge_m(plan)
    assert legend.dxf.attachment_point in {1, 4, 7}  # точка вставки - левый край текста
    assert legend.dxf.insert.x > right


# Отрисовка ezdxf задевает устаревший приём NumPy в самой библиотеке - шум, не наш код.
@pytest.mark.filterwarnings("ignore:Setting the shape on a NumPy array:DeprecationWarning")
def test_legend_text_has_width_and_wraps_inside_it(tmp_path: Path) -> None:
    doc = ezdxf.readfile(_write(tmp_path, _mixed_plan()))
    legend = _legend(doc)
    width = legend.dxf.get("width") or 0.0
    assert width > 0
    # Строка цитаты длиннее ширины: без переноса она ушла бы за правый край колонки.
    longest = max(len(line) for line in legend.plain_text().split("\n"))
    assert longest * legend.dxf.char_height * 0.5 > width
    # Движок отрисовки ezdxf переносит строки по ширине, как CAD: текст не выходит из колонки.
    recorder = Recorder()
    Frontend(RenderContext(doc), recorder).draw_entities([legend])
    rendered = recorder.player().bbox()
    assert rendered.extmax.x <= legend.dxf.insert.x + width * 1.01


def test_layout_is_in_drawing_units_for_millimetre_drawing(tmp_path: Path) -> None:
    plan = _mixed_plan()
    metres = ezdxf.readfile(_write(tmp_path, plan))
    millimetres = ezdxf.readfile(_write(tmp_path, plan, unit_m=MM))
    left, right = _schedule_span(millimetres)
    legend = _legend(millimetres)
    assert left > _plan_right_edge_m(plan) / MM
    assert legend.dxf.insert.x > right
    # Раскладка чертежа в мм - та же, что в метрах, умноженная на 1000: отступы тоже в единицах.
    for drawn_m, drawn_mm in (
        (_schedule_span(metres), (left, right)),
        (_legend_frame(_legend(metres)), _legend_frame(legend)),
    ):
        for value_m, value_mm in zip(drawn_m, drawn_mm, strict=True):
            assert math.isclose(value_mm, value_m / MM, rel_tol=1e-9)
    for insert in _plantings(millimetres):
        assert math.isclose(_attr(insert, "POS").dxf.height, LABEL_HEIGHT_M / MM, rel_tol=1e-6)


# --- план без посадок --------------------------------------------------------------------------


@pytest.mark.parametrize("content", ["rejections", "lawns"])
def test_plan_without_plantings_puts_legend_beyond_what_exists(
    tmp_path: Path, content: str
) -> None:
    if content == "rejections":
        plan = Plan((), (_rejection(1, X0), _rejection(2, X0 + 30)))
    else:
        plan = Plan((), (), lawns=(_lawn(X0, X0 + 30),))
    doc = ezdxf.readfile(_write(tmp_path, plan))
    msp = doc.modelspace()
    assert not msp.query(f"*[layer=='{LAYER_SCHEDULE}']")  # нет посадок - нет строк ведомости
    assert not _position_labels(doc)  # и нет подписей позиций: номер отказа - атрибут отметки
    legend = _legend(doc)
    assert legend.dxf.insert.x > _plan_right_edge_m(plan)
    assert legend.dxf.insert.y >= Y0


def test_empty_plan_draws_no_legend_and_no_schedule(tmp_path: Path) -> None:
    doc = ezdxf.readfile(_write(tmp_path, Plan((), ())))
    msp = doc.modelspace()
    assert not msp.query(f"MTEXT[layer=='{LAYER_LABELS}']")
    assert not msp.query(f"*[layer=='{LAYER_SCHEDULE}']")
    assert not _position_labels(doc)


# --- сверка экспорта ---------------------------------------------------------------------------


def test_export_check_accepts_written_schedule_positions(tmp_path: Path) -> None:
    plan = _mixed_plan()
    assert check_written_plan(_write(tmp_path, plan), plan, unit_m=1.0).ok


@pytest.mark.parametrize("mutation", ["wrong", "missing"])
def test_export_check_flags_position_not_matching_schedule(tmp_path: Path, mutation: str) -> None:
    plan = _mixed_plan()
    target = _write(tmp_path, plan)
    doc = ezdxf.readfile(target)
    spirea = next(i for i in _plantings(doc) if _attr(i, "NUM").dxf.text == "3")
    if mutation == "wrong":
        _attr(spirea, "POS").dxf.text = "3"  # сквозной номер вместо позиции ведомости
    else:
        spirea.delete_attrib("POS", ignore=True)
    doc.saveas(target)
    report = check_written_plan(target, plan, unit_m=1.0)
    assert not report.ok
    assert any(issue.startswith("p3:") and "POS" in issue for issue in report.issues)


@pytest.mark.parametrize("mutation", ["wrong", "missing", "duplicate", "moved"])
def test_export_check_flags_position_text_not_matching_schedule(
    tmp_path: Path, mutation: str
) -> None:
    plan = _mixed_plan()
    target = _write(tmp_path, plan)
    doc = ezdxf.readfile(target)
    msp = doc.modelspace()
    label = next((t for t in _position_labels(doc) if _identity(t) == "p3"), None)
    assert label is not None, "у спиреи нет подписи позиции"
    if mutation == "wrong":
        label.dxf.text = "3"  # сквозной номер вместо позиции ведомости
    elif mutation == "missing":
        msp.delete_entity(label)
    elif mutation == "duplicate":
        msp.add_entity(label.copy())
    else:
        label.dxf.insert = label.dxf.insert.replace(x=label.dxf.insert.x + 1.0)  # на метр в сторону
    doc.saveas(target)
    report = check_written_plan(target, plan, unit_m=1.0)
    assert not report.ok
    assert any(issue.startswith("p3:") and "подпись позиции" in issue for issue in report.issues)


def test_export_check_flags_position_text_of_unknown_planting(tmp_path: Path) -> None:
    plan = _mixed_plan()
    target = _write(tmp_path, plan)
    doc = ezdxf.readfile(target)
    label = next((t for t in _position_labels(doc) if _identity(t) == "p3"), None)
    assert label is not None, "у спиреи нет подписи позиции"
    label.set_xdata("LCT_GREEN", [(1000, "p99")])
    doc.saveas(target)
    issues = check_written_plan(target, plan, unit_m=1.0).issues
    assert any(issue.startswith("p99:") and "подпись позиции" in issue for issue in issues)
    assert any(issue.startswith("p3:") and "подпись позиции" in issue for issue in issues)
