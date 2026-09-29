"""Фото по кадру 3D-вида: промпт режимов, проверка кадра, очередь и HTTP API.

Модель в тестах не запускается: вместо неё рендерер, который копирует кадр. Настоящий прогон
Qwen-Image-2.1 проверяется руками (docs/notes/40-scene-photos.md), он идёт минуту на кадр.
"""

from __future__ import annotations

import shutil
import struct
import zlib
from concurrent.futures import Executor, Future
from dataclasses import replace
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient
from test_pipeline_synthetic import ROOT

from green.application.errors import InputError
from green.application.photos import (
    PhotoError,
    PhotoOptions,
    PhotoService,
    PhotoState,
    PhotoUnavailableError,
    build_prompt,
    check_source,
    light_of,
    species_names,
)
from green.bootstrap.container import build_container
from green.bootstrap.settings import Settings
from green.infrastructure.photo.sdcpp import SdCppPhotoRenderer
from green.infrastructure.storage.photos import FileSystemPhotoStore
from green.infrastructure.storage.runs import FileSystemRunStore
from green.interfaces.api.app import API_PREFIX, create_app

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from pathlib import Path

    from green.application.photos import PhotoPrompt


def _png(width: int, height: int) -> bytes:
    """Настоящий PNG заданного размера: одна серая строка, повторённая height раз."""
    row = b"\x00" + b"\x80" * width
    raw = zlib.compress(row * height)

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    header = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", raw) + chunk(b"IEND", b"")


class InlineExecutor(Executor):
    """Задание выполняется сразу, в том же потоке: тесту не нужно ждать очередь."""

    def submit[T](self, fn: Callable[..., T], /, *args: object, **kwargs: object) -> Future[T]:
        future: Future[T] = Future()
        future.set_result(fn(*args, **kwargs))
        return future


class CopyRenderer:
    """Вместо модели: выход - копия кадра, увеличенного фото нет."""

    def __init__(self, fail: str | None = None) -> None:
        self.fail = fail
        self.prompts: list[PhotoPrompt] = []

    def unavailable_reason(self) -> str | None:
        return None

    def render(
        self, *, source: Path, raw: Path, photo: Path, prompt: PhotoPrompt, size: tuple[int, int]
    ) -> bool:
        del photo, size
        self.prompts.append(prompt)
        if self.fail:
            raise PhotoError(self.fail)
        shutil.copyfile(source, raw)
        return False


def test_default_prompt_keeps_the_plan_and_scenery_adds_haze() -> None:
    plain = build_prompt(PhotoOptions())
    scenery = build_prompt(PhotoOptions(scenery=True))

    assert "Keep the exact composition" in plain.text
    assert "haze" not in plain.text
    assert "Add nothing" in plain.text
    assert "birch" not in plain.text
    assert "extra trees" in plain.negative
    assert "haze" in scenery.text
    assert "not topiary" in scenery.text
    assert "topiary" in scenery.negative
    assert "3d render" in plain.negative
    assert (plain.steps, plain.cfg) == (25, 4.0)


def test_prompt_follows_season_hour_viewpoint_and_species() -> None:
    prompt = build_prompt(
        PhotoOptions(
            season="winter",
            hour=19.5,
            viewpoint="ground",
            species=("Tilia cordata",),
            shrubs=("Spiraea vanhouttei",),
        )
    )

    assert "winter" in prompt.text
    assert "evening golden light" in prompt.text
    assert "eye level from the sidewalk of a residential street" in prompt.text
    assert "the trees in the render are Tilia cordata" in prompt.text
    assert "bare branches" in prompt.text
    assert "the shrubs in the render are Spiraea vanhouttei" in prompt.text


@pytest.mark.parametrize(
    ("hour", "light"),
    [(3.0, "night"), (7.0, "early morning"), (11.0, "late morning"), (23.0, "night")],
)
def test_light_follows_the_hour(hour: float, light: str) -> None:
    assert light in light_of(hour)


def test_source_must_be_png_with_sides_divisible_by_32() -> None:
    assert check_source(_png(1024, 576)) == (1024, 576)
    with pytest.raises(InputError, match="PNG"):
        check_source(b"not a png at all, just text bytes")
    with pytest.raises(InputError, match="кратны 32"):
        check_source(_png(1000, 576))
    with pytest.raises(InputError, match="кратны 32"):
        check_source(_png(4096, 576))


def test_species_names_are_unique_trimmed_and_capped() -> None:
    names = species_names([" Tilia  cordata ", "Tilia cordata", "", *[f"S{i}" for i in range(9)]])

    assert names[0] == "Tilia cordata"
    assert len(names) == 6


@pytest.fixture
def runs(tmp_path: Path) -> FileSystemRunStore:
    return FileSystemRunStore(tmp_path / "runs")


def test_service_renders_and_stores_the_photo(runs: FileSystemRunStore) -> None:
    run = runs.create("street.dxf", "strict", {})
    renderer = CopyRenderer()
    service = PhotoService(FileSystemPhotoStore(runs), renderer, executor=InlineExecutor())

    job = service.submit(run.run_id, _png(512, 288), PhotoOptions(scenery=True))
    done = service.get(run.run_id, job.id)

    assert done.state is PhotoState.SUCCEEDED
    assert done.seconds is not None
    assert not done.upscaled
    assert service.file(run.run_id, job.id, "photo").name == "raw.png"
    assert "haze" in renderer.prompts[0].text
    assert [j.id for j in service.jobs(run.run_id)] == [job.id]


def test_failed_render_keeps_the_reason(runs: FileSystemRunStore) -> None:
    run = runs.create("street.dxf", "strict", {})
    service = PhotoService(
        FileSystemPhotoStore(runs), CopyRenderer(fail="out of memory"), executor=InlineExecutor()
    )

    job = service.submit(run.run_id, _png(512, 288), PhotoOptions())

    failed = service.get(run.run_id, job.id)
    assert failed.state is PhotoState.FAILED
    assert failed.error == "out of memory"


def test_job_left_by_a_previous_process_reads_as_interrupted(runs: FileSystemRunStore) -> None:
    run = runs.create("street.dxf", "strict", {})
    store = FileSystemPhotoStore(runs)

    class Never(Executor):
        def submit(self, fn: object, /, *args: object, **kwargs: object) -> Future[None]:
            del fn, args, kwargs
            return Future()

    job = PhotoService(store, CopyRenderer(), executor=Never()).submit(
        run.run_id, _png(512, 288), PhotoOptions()
    )
    restarted = PhotoService(store, CopyRenderer(), executor=InlineExecutor())

    seen = restarted.get(run.run_id, job.id)
    assert seen.state is PhotoState.FAILED
    assert seen.error is not None
    assert "перезапуском" in seen.error


def test_service_without_renderer_refuses(runs: FileSystemRunStore) -> None:
    run = runs.create("street.dxf", "strict", {})
    service = PhotoService(FileSystemPhotoStore(runs), None)

    assert service.unavailable_reason is not None
    with pytest.raises(PhotoUnavailableError):
        service.submit(run.run_id, _png(512, 288), PhotoOptions())


def test_sdcpp_renderer_names_missing_model_files(tmp_path: Path) -> None:
    reason = SdCppPhotoRenderer(models_dir=tmp_path).unavailable_reason()

    assert reason is not None
    assert "qwen-image-2.1-Q4_K_S.gguf" in reason


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    settings = Settings(config_dir=ROOT / "config", runs_dir=tmp_path / "runs")
    container = build_container(settings)
    service = PhotoService(
        FileSystemPhotoStore(container.store), CopyRenderer(), executor=InlineExecutor()
    )
    with TestClient(create_app(replace(container, photos=service))) as c:
        yield c


def test_api_queues_a_photo_and_serves_the_files(client: TestClient) -> None:
    store = client.app.state.container.store  # type: ignore[attr-defined]
    run = store.create("street.dxf", "strict", {})

    listed = client.get(f"{API_PREFIX}/runs/{run.run_id}/photos").json()
    assert listed == {"available": True, "reason": None, "photos": []}

    response = client.post(
        f"{API_PREFIX}/runs/{run.run_id}/photos",
        files={"image": ("shot.png", _png(512, 288), "image/png")},
        data={
            "scenery": "true",
            "season": "autumn",
            "hour": "16",
            "species": "Tilia cordata",
            "shot": "Участок 1 из 3",
        },
    )
    assert response.status_code == 202, response.text
    photo = client.get(response.headers["Location"]).json()
    assert photo["state"] == "succeeded"
    assert photo["scenery"] is True
    assert photo["species"] == ["Tilia cordata"]
    assert photo["shot"] == "Участок 1 из 3"

    image = client.get(photo["photo_url"])
    assert image.status_code == 200
    assert image.headers["content-type"] == "image/png"
    assert client.get(photo["source_url"]).content.startswith(b"\x89PNG")


def test_api_rejects_bad_frames_and_unknown_photos(client: TestClient) -> None:
    store = client.app.state.container.store  # type: ignore[attr-defined]
    run = store.create("street.dxf", "strict", {})

    bad = client.post(
        f"{API_PREFIX}/runs/{run.run_id}/photos",
        files={"image": ("shot.png", _png(500, 288), "image/png")},
    )
    assert bad.status_code == 422
    assert client.get(f"{API_PREFIX}/runs/{run.run_id}/photos/0123456789ab").status_code == 404
    assert client.get(f"{API_PREFIX}/runs/{run.run_id}/photos/..%2f..").status_code in {404, 422}


def test_api_says_why_photos_are_unavailable(tmp_path: Path) -> None:
    settings = Settings(config_dir=ROOT / "config", runs_dir=tmp_path / "runs")
    with TestClient(create_app(build_container(settings))) as c:
        run = c.app.state.container.store.create("street.dxf", "strict", {})  # type: ignore[attr-defined]
        listed = c.get(f"{API_PREFIX}/runs/{run.run_id}/photos").json()
        refused = c.post(
            f"{API_PREFIX}/runs/{run.run_id}/photos",
            files={"image": ("shot.png", _png(512, 288), "image/png")},
        )

    assert listed["available"] is False
    assert "GREEN_PHOTO_MODELS_DIR" in listed["reason"]
    assert refused.status_code == 503


def test_frame_with_alpha_is_flattened_on_white(tmp_path: Path) -> None:
    from PIL import Image  # noqa: PLC0415 - Pillow нужен только этому тесту

    from green.infrastructure.photo.sdcpp import _to_rgb  # noqa: PLC0415

    source = tmp_path / "source.png"
    image = Image.new("RGBA", (64, 32), (10, 120, 40, 255))
    image.putpixel((0, 0), (0, 0, 0, 0))
    image.save(source)

    _to_rgb(source, tmp_path / "input.png")

    with Image.open(tmp_path / "input.png") as flat:
        assert flat.mode == "RGB"
        assert flat.getpixel((0, 0)) == (255, 255, 255)
        assert flat.getpixel((5, 5)) == (10, 120, 40)


def test_modern_facades_keep_the_volume_and_can_be_switched_off() -> None:
    modern = build_prompt(PhotoOptions())
    plain = build_prompt(PhotoOptions(modern=False))

    assert "number of floors" in modern.text
    assert "clinker brick" in modern.text
    assert "khrushchevka" in modern.negative
    assert "clinker" not in plain.text
    assert "khrushchevka" not in plain.negative


def test_custom_prompt_replaces_the_built_one() -> None:
    from green.application.photos import prompt_for  # noqa: PLC0415

    custom = prompt_for(PhotoOptions(custom_text="  my prompt  ", custom_negative=""))
    built = prompt_for(PhotoOptions())

    assert custom.text == "my prompt"
    assert custom.negative == build_prompt(PhotoOptions()).negative
    assert built == build_prompt(PhotoOptions())


def test_api_previews_the_prompt_and_takes_a_custom_one(client: TestClient) -> None:
    store = client.app.state.container.store  # type: ignore[attr-defined]
    run = store.create("street.dxf", "strict", {})

    preview = client.get(
        f"{API_PREFIX}/runs/{run.run_id}/photos/prompt",
        params={"modern": "false", "viewpoint": "ground"},
    ).json()
    assert "eye level" in preview["text"]
    assert "clinker" not in preview["text"]

    response = client.post(
        f"{API_PREFIX}/runs/{run.run_id}/photos",
        files={"image": ("shot.png", _png(512, 288), "image/png")},
        data={"prompt": "a photo of a quiet street", "modern": "false"},
    )
    photo = client.get(response.headers["Location"]).json()
    assert photo["custom"] is True
    assert photo["modern"] is False


def test_api_deletes_a_finished_photo(client: TestClient) -> None:
    store = client.app.state.container.store  # type: ignore[attr-defined]
    run = store.create("street.dxf", "strict", {})
    created = client.post(
        f"{API_PREFIX}/runs/{run.run_id}/photos",
        files={"image": ("shot.png", _png(512, 288), "image/png")},
    )
    location = created.headers["Location"]

    assert client.delete(location).status_code == 204
    assert client.get(location).status_code == 404
    assert client.get(f"{API_PREFIX}/runs/{run.run_id}/photos").json()["photos"] == []
    assert client.delete(location).status_code == 404


def test_photo_in_work_is_not_deleted(runs: FileSystemRunStore) -> None:
    from green.application.photos import PhotoBusyError  # noqa: PLC0415

    run = runs.create("street.dxf", "strict", {})

    class Never(Executor):
        def submit(self, fn: object, /, *args: object, **kwargs: object) -> Future[None]:
            del fn, args, kwargs
            return Future()

    service = PhotoService(FileSystemPhotoStore(runs), CopyRenderer(), executor=Never())
    job = service.submit(run.run_id, _png(512, 288), PhotoOptions())

    with pytest.raises(PhotoBusyError):
        service.delete(run.run_id, job.id)
