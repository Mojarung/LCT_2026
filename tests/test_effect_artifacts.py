"""Эффект «было - стало» в прогоне: quality.json, отчёт интерпретаций (MD и HTML)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import ezdxf
import orjson
import pytest
from test_pipeline_synthetic import ROOT, _street

from green.application.use_case import PlanRequest
from green.bootstrap.container import build_container
from green.bootstrap.settings import Settings

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture(scope="module")
def run(tmp_path_factory: pytest.TempPathFactory) -> dict[str, object]:
    work = tmp_path_factory.mktemp("effect")
    source = work / "street.dxf"
    _street(source)
    doc = ezdxf.readfile(source)
    doc.layers.add("Отдельно стоящее дерево")
    doc.modelspace().add_circle((60.0, 30.0), 0.3, dxfattribs={"layer": "Отдельно стоящее дерево"})
    doc.saveas(source)
    container = build_container(Settings(config_dir=ROOT / "config", runs_dir=work / "runs"))
    params = container.profiles.load("strict", {"max_rejections": 50})
    report = container.use_case.execute(PlanRequest("e", source, work / "out", "strict", params))
    return {"report": report, "artifacts": container.artifacts.save(work / "out", report)}


def _read(run: dict[str, object], name: str) -> Path:
    return run["artifacts"][name]  # type: ignore[index]


def test_plan_carries_the_effect(run: dict[str, object]) -> None:
    effect = run["report"].plan.effect  # type: ignore[attr-defined]
    assert effect is not None
    # Дерево нарисовано кругом, а не вставкой знака: штуки по чертежу не выводятся, кроны - да.
    trees = next(m for m in effect.measures if m.key == "trees")
    assert trees.before is None
    assert "не определяется" in trees.note
    canopy = next(m for m in effect.measures if m.key == "canopy_m2")
    assert canopy.before > 0
    assert canopy.after > canopy.before


def test_quality_json_has_the_effect_block(run: dict[str, object]) -> None:
    quality = orjson.loads(_read(run, "quality.json").read_bytes())
    effect = quality["effect"]
    keys = {m["key"] for m in effect["measures"]}
    assert {"trees", "shrubs", "canopy_m2", "curb_green_m", "tiers_trees", "noise_curb_m"} <= keys
    assert {k["key"] for k in effect["kinds"]} & {"alley", "lawn"}
    assert next(b["width"] for b in effect["noise"]) == "10-15"


def test_readable_report_has_the_balance_and_kinds(run: dict[str, object]) -> None:
    md = _read(run, "interpretations.md").read_text(encoding="utf-8")
    html = _read(run, "report.html").read_text(encoding="utf-8")
    for text in (md, html):
        assert "Баланс озеленения и эффект" in text
        assert "Виды посадок" in text
        assert "Деревья" in text
    assert md.index("## Баланс озеленения") < md.index("## Нормативная база")
