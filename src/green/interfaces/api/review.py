"""Replay a semantic review against the exact computational drawing."""

from __future__ import annotations

import hashlib
import shutil
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Literal

import orjson
from pydantic import BaseModel, ConfigDict, Field

from green.application.errors import ConflictError, InputError
from green.application.results import RunState
from green.domain.objects import ObjectClass

if TYPE_CHECKING:
    from fastapi import BackgroundTasks

    from green.application.results import RunRecord
    from green.bootstrap.container import Container


class SemanticReviewIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    feature_classes: dict[str, ObjectClass] = Field(default_factory=dict)
    label_roles: dict[str, Literal["soil", "paved", "ignore"]] = Field(default_factory=dict)


def replay_review(
    container: Container, background: BackgroundTasks, run_id: str, body: SemanticReviewIn
) -> RunRecord:
    original = container.store.get(run_id)
    if original.state in {RunState.QUEUED, RunState.RUNNING}:
        raise ConflictError("Дождитесь окончания прогона перед уточнением")
    drawing = container.store.artifact(run_id, "review-input.dxf")
    geometry = orjson.loads(
        container.store.artifact(run_id, "semantic-review.geojson").read_bytes()
    )
    report_name = (
        "review-classification.json"
        if "review-classification.json" in original.artifacts
        else "classification.json"
    )
    report = orjson.loads(container.store.artifact(run_id, report_name).read_bytes())
    with drawing.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    if (
        digest != body.source_sha256
        or geometry["source_sha256"] != digest
        or report["source_sha256"] != digest
    ):
        raise InputError("Уточнения относятся к другому DXF: хеш исходника изменился")
    features = {str(f["id"]) for f in geometry["features"]}
    labels = {str(label["id"]) for label in geometry.get("labels", [])}
    if set(body.feature_classes) - features or set(body.label_roles) - labels:
        raise InputError("Уточнение содержит ссылки на отсутствующие объекты или подписи")
    if any(
        kind in {ObjectClass.UNKNOWN, ObjectClass.UTILITY_UNKNOWN}
        for kind in body.feature_classes.values()
    ):
        raise InputError("Выберите установленный класс объекта")
    overrides = dict(original.overrides)
    # Review exports contain all earlier explicit assignments as exact references.
    overrides.pop("layer_classes", None)
    overrides.pop("block_classes", None)
    explicit = {
        str(f["id"]): f["properties"]["class"]
        for f in geometry["features"]
        if report["groups"][f["properties"]["group"]]["evidence"]["method"].startswith("explicit_")
    }
    explicit_labels = {
        str(label["id"]): label["surface_role"]
        for label in geometry.get("labels", [])
        if (label.get("evidence") or {}).get("method") == "explicit_label"
    }
    overrides.update(
        feature_classes={
            **explicit,
            **{key: kind.value for key, kind in body.feature_classes.items()},
        },
        label_roles={**explicit_labels, **body.label_roles},
        semantic_source_sha256=digest,
        require_reviewed_objects=True,
    )
    # Registering can prune completed runs. Stage donor inputs before that happens.
    with tempfile.TemporaryDirectory(prefix="green-review-") as temporary:
        stage = Path(temporary)
        shutil.copy2(drawing, stage / "drawing.dxf")
        input_dir = container.store.input_path(run_id).parent
        inventories = list(input_dir.glob("inventory.xls*"))
        if inventories:
            shutil.copy2(inventories[0], stage / inventories[0].name)
        if (input_dir / "gis").is_dir():
            shutil.copytree(input_dir / "gis", stage / "gis")
        record = container.runs.register("review-input.dxf", original.profile, overrides)
        try:
            target = container.store.input_path(record.run_id)
            shutil.copy2(stage / "drawing.dxf", target)
            inventory = None
            if inventories:
                inventory = target.with_name(inventories[0].name)
                shutil.copy2(stage / inventories[0].name, inventory)
            gis = ()
            if (stage / "gis").is_dir():
                shutil.copytree(stage / "gis", target.parent / "gis")
                gis = tuple(sorted((target.parent / "gis").iterdir()))
        except OSError as error:
            container.runs.reject(record.run_id, str(error))
            raise InputError("Не удалось сохранить входы для повторного расчёта") from error
    background.add_task(container.runs.execute, record.run_id, inventory, gis_layers=gis)
    return record
