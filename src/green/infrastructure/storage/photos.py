"""Задания фото на диске: каталог photos/<id> рядом со status.json прогона.

Фото - не артефакт прогона: оно появляется после него, по запросу из 3D-вида, и в список
артефактов (и в пересборку DXF) не входит. Удаляется вместе с каталогом прогона.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import TYPE_CHECKING, Any

import orjson

from green.application.errors import NotFoundError
from green.application.photos import PhotoJob, PhotoOptions, PhotoState

if TYPE_CHECKING:
    from pathlib import Path

    from green.application.ports import PhotoFile
    from green.infrastructure.storage.runs import FileSystemRunStore

JOB = "job.json"
FILES: dict[str, str] = {"source": "source.png", "raw": "raw.png", "photo": "photo.jpg"}
_PHOTO_ID = re.compile(r"[0-9a-f]{12}")


class FileSystemPhotoStore:
    def __init__(self, runs: FileSystemRunStore) -> None:
        self._runs = runs

    def create(self, job: PhotoJob, source: bytes) -> None:
        self._runs.get(job.run_id)
        folder = self._dir(job.run_id, job.id)
        folder.mkdir(parents=True, exist_ok=False)
        (folder / FILES["source"]).write_bytes(source)
        self.save(job)

    def save(self, job: PhotoJob) -> None:
        path = self._dir(job.run_id, job.id) / JOB
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(orjson.dumps(_payload(job), option=orjson.OPT_INDENT_2))
        tmp.replace(path)

    def get(self, run_id: str, photo_id: str) -> PhotoJob:
        path = self._dir(run_id, photo_id) / JOB
        if not path.is_file():
            raise NotFoundError(f"Фото {photo_id} не найдено")
        return _job(orjson.loads(path.read_bytes()))

    def jobs(self, run_id: str) -> list[PhotoJob]:
        self._runs.get(run_id)
        root = self._runs.state_file(run_id, "photos")
        if not root.is_dir():
            return []
        jobs = [
            _job(orjson.loads((folder / JOB).read_bytes()))
            for folder in root.iterdir()
            if _PHOTO_ID.fullmatch(folder.name) and (folder / JOB).is_file()
        ]
        return sorted(jobs, key=lambda job: job.created_at, reverse=True)

    def path(self, run_id: str, photo_id: str, kind: PhotoFile) -> Path:
        path = self._dir(run_id, photo_id) / FILES[kind]
        if kind == "source" and not path.is_file():
            raise NotFoundError(f"Кадр фото {photo_id} не найден")
        return path

    def _dir(self, run_id: str, photo_id: str) -> Path:
        if not _PHOTO_ID.fullmatch(photo_id):
            raise NotFoundError(f"Фото {photo_id} не найдено")
        return self._runs.state_file(run_id, "photos") / photo_id


def _payload(job: PhotoJob) -> dict[str, object]:
    o = job.options
    return {
        "id": job.id,
        "run_id": job.run_id,
        "state": job.state.value,
        "width": job.width,
        "height": job.height,
        "created_at": job.created_at.isoformat(),
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        "error": job.error,
        "upscaled": job.upscaled,
        "options": {
            "scenery": o.scenery,
            "season": o.season,
            "hour": o.hour,
            "viewpoint": o.viewpoint,
            "species": list(o.species),
            "shrubs": list(o.shrubs),
        },
    }


def _when(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _job(data: dict[str, Any]) -> PhotoJob:
    o = data["options"]
    return PhotoJob(
        id=data["id"],
        run_id=data["run_id"],
        options=PhotoOptions(
            scenery=bool(o["scenery"]),
            season=o["season"],
            hour=float(o["hour"]),
            viewpoint=o["viewpoint"],
            species=tuple(o["species"]),
            shrubs=tuple(o.get("shrubs", ())),
        ),
        width=int(data["width"]),
        height=int(data["height"]),
        state=PhotoState(data["state"]),
        created_at=datetime.fromisoformat(data["created_at"]),
        started_at=_when(data["started_at"]),
        finished_at=_when(data["finished_at"]),
        error=data["error"],
        upscaled=bool(data["upscaled"]),
    )
