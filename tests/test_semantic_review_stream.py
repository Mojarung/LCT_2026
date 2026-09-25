"""A failed review export must not replace a previously complete artifact."""

from __future__ import annotations

from typing import TYPE_CHECKING

import ezdxf
import pytest

from green.application.classification import LayerMap, classification_report, classify_scene
from green.infrastructure.cad.reader import EzdxfSceneReader
from green.infrastructure.reports import semantic_review

if TYPE_CHECKING:
    from pathlib import Path


def test_failed_review_stream_keeps_previous_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    doc = ezdxf.new("R2018")
    doc.modelspace().add_line((0, 0), (1, 1))
    source = tmp_path / "drawing.dxf"
    doc.saveas(source)
    scene, _ = classify_scene(EzdxfSceneReader().read(source), LayerMap((), "test"))
    report = classification_report(scene, LayerMap((), "test"))
    previous = tmp_path / "semantic-review.geojson"
    previous.write_bytes(b"previous complete artifact")

    def fail_mapping(_geometry: object) -> None:
        raise RuntimeError("serialization stopped")

    monkeypatch.setattr(semantic_review, "mapping", fail_mapping)
    with pytest.raises(RuntimeError, match="serialization stopped"):
        semantic_review.save_review_geometry(tmp_path, report, scene, None)
    assert previous.read_bytes() == b"previous complete artifact"
    assert not (tmp_path / ".semantic-review.geojson.tmp").exists()
