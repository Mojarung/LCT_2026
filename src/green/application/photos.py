"""Фото участка по кадру 3D-вида: промпт, проверка кадра, очередь заданий.

3D-вид строит сцену из артефактов прогона, и каждое дерево на его кадре стоит в точке плана.
Генеративная модель правки (Qwen-Image-2.1) перерисовывает такой кадр в фотографию, сохраняя
расстановку: это бонус ТЗ - реалистичная визуализация, согласованная с планом. Картинка по
одному тексту для этого не годится: она нарисует чужую улицу.

Два режима, подобранных на кадре облёта (docs/notes/40-scene-photos.md):
- по умолчанию - только то, что есть в кадре: негативный промпт против «рендерности», CFG 4;
- «фон и деревья» - модель дорисовывает город в дымке у горизонта и естественные группы
  кустарника и деревьев на пустых газонах. Картинка живее, но на ней есть то, чего нет в плане.

Модель занимает всю видеопамять и считает минуту-две на кадр, поэтому задания идут по одному.
"""

from __future__ import annotations

import struct
import threading
from concurrent.futures import Executor, ThreadPoolExecutor
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Literal
from uuid import uuid4

from green.application.errors import GreenError, InputError, NotFoundError

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from pathlib import Path

    from green.application.ports import PhotoRenderer, PhotoStore

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
# Модель работает латентами 16 x 16 пикселей и режет стороны кратно 32.
SIDE_STEP = 32
SIDE_MIN = 256
SIDE_MAX = 2048
MAX_SOURCE_BYTES = 16 * 2**20
MAX_SPECIES = 6
STEPS = 25
CFG = 4.0

type Season = Literal["spring", "summer", "autumn", "winter"]
type Viewpoint = Literal["aerial", "ground"]


class PhotoUnavailableError(GreenError):
    """Генерация фото не настроена на этом сервере: нет модели или программы."""


class PhotoError(GreenError):
    """Модель не выдала фото: ошибка программы, нехватка памяти или время вышло."""


class PhotoState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class PhotoOptions:
    # Дорисовать город у горизонта и естественные группы кустарника и деревьев на газонах.
    scenery: bool = False
    season: Season = "summer"
    hour: float = 11.0
    viewpoint: Viewpoint = "aerial"
    # Латинские названия видов в кадре: модель рисует липу липой, а не абстрактным деревом.
    species: tuple[str, ...] = ()
    shrubs: tuple[str, ...] = ()
    # Подпись кадра («Участок 1 из 3», «№ 12. Клён, с юга»): по ней галерея узнаёт фото кадра.
    shot: str = ""


@dataclass(frozen=True, slots=True)
class PhotoPrompt:
    text: str
    negative: str
    steps: int = STEPS
    cfg: float = CFG


@dataclass(frozen=True, slots=True)
class PhotoJob:
    id: str
    run_id: str
    options: PhotoOptions
    width: int
    height: int
    state: PhotoState
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error: str | None = None
    # Есть ли увеличенная версия: без апскейлера на сервере остаётся только выход модели.
    upscaled: bool = False

    @property
    def seconds(self) -> float | None:
        if self.started_at is None or self.finished_at is None:
            return None
        return round((self.finished_at - self.started_at).total_seconds(), 1)


SEASONS: dict[str, str] = {
    "spring": "late spring",
    "summer": "early summer",
    "autumn": "mid autumn",
    "winter": "winter, snow on the ground and on the branches",
}

FOLIAGE: dict[str, str] = {
    "spring": "fresh young leaves",
    "summer": "natural dense leaves",
    "autumn": "yellow, orange and red autumn leaves",
    "winter": "bare branches, conifers stay green",
}

NEGATIVE = (
    "3d render, CGI, video game, low poly, cartoon, illustration, plastic, flat textures, "
    "oversaturated, blurry, text, watermark, user interface"
)
SCENERY_NEGATIVE = f"{NEGATIVE}, topiary, clipped round bushes, empty flat horizon, blue foliage"
# В режиме по плану модель охотно досаживала берёзы у стен и изгородь вдоль ограды: запрет прямо.
PLAN_NEGATIVE = (
    f"{NEGATIVE}, extra trees, additional trees, new trees, trees in front of the building, "
    "hedge, extra bushes, added vegetation, fence replaced by bushes"
)


def light_of(hour: float) -> str:
    """Свет по часу: те же сутки, что у солнца 3D-вида."""
    bands = (
        (5.0, "early morning, low sun"),
        (9.0, "late morning sun"),
        (12.0, "midday sun"),
        (15.0, "afternoon sun"),
        (18.0, "evening golden light"),
        (21.0, "night, street lamps lit"),
    )
    label = "night, street lamps lit"
    for start, text in bands:
        if hour >= start:
            label = text
    return label


def build_prompt(options: PhotoOptions) -> PhotoPrompt:
    """Промпт правки. Текст - тот, что подобран на кадре облёта, с подстановкой сезона,
    часа, точки съёмки и видов из плана."""
    if options.viewpoint == "ground":
        view = "real photograph taken at eye level from the sidewalk of"
        camera = "a full-frame camera, 35mm lens"
    else:
        view = "real aerial photograph taken from a drone over"
        camera = "a DJI Mavic 3, 24mm lens"
    foliage = FOLIAGE[options.season]
    lead = (
        f"Transform this 3D render into a {view} a residential street in Moscow in "
        f"{SEASONS[options.season]}, {light_of(options.hour)}. "
    )
    finish = f" Photorealistic, natural colors, sharp, high detail, shot on {camera}."
    if options.scenery:
        trees = (
            ", ".join(options.species[:MAX_SPECIES]) + " trees"
            if options.species
            else "young linden, maple and birch trees"
        )
        kinds = f" ({', '.join(options.shrubs[:MAX_SPECIES])})" if options.shrubs else ""
        text = (
            lead + "Keep the exact composition and every object in its place: the buildings, the "
            "road, curbs, sidewalks, street lamps and every tree and shrub at the same position "
            f"and size. Make everything look real: {trees} with {foliage} and visible branches, "
            f"loose natural groups of flowering and evergreen shrubs{kinds} of different heights "
            "(not topiary, not clipped balls), mowed lawn with slight unevenness, worn grey "
            "asphalt with patches, concrete curbs, paving tiles, real facades with balconies and "
            "window frames, soft realistic shadows. All foliage in natural greens, no blue or "
            "cyan tints. Behind the street, in the distance, other residential blocks and trees "
            "fade into light haze instead of an empty field." + finish
        )
        return PhotoPrompt(text=text, negative=SCENERY_NEGATIVE)
    # По плану: только материалы, ни одного нового объекта. Породы называются, лишь когда они
    # есть в кадре, - иначе модель брала «липу, клён и берёзу» как приглашение их посадить.
    trees = (
        f"the trees in the render are {', '.join(options.species[:MAX_SPECIES])}"
        if options.species
        else "the trees that are in the render"
    )
    shrubs = (
        f"; the shrubs in the render are {', '.join(options.shrubs[:MAX_SPECIES])}"
        if options.shrubs
        else ""
    )
    text = (
        lead + "Keep the exact composition and every object in its place and size: the buildings, "
        "the road, curbs, sidewalks, fences, street lamps, people, trees and shrubs. Add nothing: "
        "no new trees, shrubs, hedges, buildings or cars; where the render shows bare lawn, "
        "pavement or wall, keep it bare. Only make the materials real: "
        f"{trees}, with {foliage} and visible branches{shrubs}; mowed lawn with slight "
        "unevenness, worn grey asphalt with patches, concrete curbs, paving tiles, metal fences, "
        "real facades with window frames, soft realistic shadows." + finish
    )
    negative = PLAN_NEGATIVE
    return PhotoPrompt(text=text, negative=negative)


def png_size(data: bytes) -> tuple[int, int]:
    """Ширина и высота PNG из заголовка IHDR; не PNG - ошибка входа."""
    if len(data) < 24 or not data.startswith(PNG_SIGNATURE) or data[12:16] != b"IHDR":  # noqa: PLR2004 - сигнатура 8 байт, длина и тип блока ещё 8, размеры - 8
        raise InputError("Кадр должен быть PNG")
    width, height = struct.unpack(">II", data[16:24])
    return width, height


def check_source(data: bytes) -> tuple[int, int]:
    if len(data) > MAX_SOURCE_BYTES:
        raise InputError("Кадр больше 16 МБ: для фото хватает 1024 x 576")
    width, height = png_size(data)
    for side in (width, height):
        if side % SIDE_STEP or not SIDE_MIN <= side <= SIDE_MAX:
            raise InputError(
                f"Стороны кадра должны быть кратны {SIDE_STEP} и лежать в пределах "
                f"{SIDE_MIN}-{SIDE_MAX} пикселей, а не {width} x {height}"
            )
    return width, height


def _now() -> datetime:
    return datetime.now(UTC)


class PhotoService:
    """Очередь фото. Задание, начатое прежним процессом сервиса, читается как прерванное."""

    def __init__(
        self,
        store: PhotoStore,
        renderer: PhotoRenderer | None,
        executor: Executor | None = None,
        clock: Callable[[], datetime] = _now,
    ) -> None:
        self._store = store
        self._renderer = renderer
        self._executor = executor or ThreadPoolExecutor(max_workers=1, thread_name_prefix="photo")
        self._clock = clock
        self._active: set[str] = set()
        self._guard = threading.Lock()

    @property
    def unavailable_reason(self) -> str | None:
        if self._renderer is None:
            return "Генерация фото на сервере не настроена (GREEN_PHOTO_MODELS_DIR)"
        return self._renderer.unavailable_reason()

    def submit(self, run_id: str, source: bytes, options: PhotoOptions) -> PhotoJob:
        reason = self.unavailable_reason
        if reason is not None or self._renderer is None:
            raise PhotoUnavailableError(reason)
        width, height = check_source(source)
        job = PhotoJob(
            id=uuid4().hex[:12],
            run_id=run_id,
            options=options,
            width=width,
            height=height,
            state=PhotoState.QUEUED,
            created_at=self._clock(),
        )
        self._store.create(job, source)
        with self._guard:
            self._active.add(job.id)
        self._executor.submit(self._render, job)
        return job

    def get(self, run_id: str, photo_id: str) -> PhotoJob:
        return self._alive(self._store.get(run_id, photo_id))

    def jobs(self, run_id: str) -> list[PhotoJob]:
        return [self._alive(job) for job in self._store.jobs(run_id)]

    def file(self, run_id: str, photo_id: str, kind: Literal["source", "raw", "photo"]) -> Path:
        job = self.get(run_id, photo_id)
        if kind != "source" and job.state is not PhotoState.SUCCEEDED:
            raise NotFoundError("Фото ещё не готово")
        if kind == "photo" and not job.upscaled:
            kind = "raw"
        return self._store.path(run_id, photo_id, kind)

    def _alive(self, job: PhotoJob) -> PhotoJob:
        if job.state not in {PhotoState.QUEUED, PhotoState.RUNNING}:
            return job
        with self._guard:
            if job.id in self._active:
                return job
        return replace(job, state=PhotoState.FAILED, error="Задание прервано перезапуском сервиса")

    def _render(self, job: PhotoJob) -> None:
        renderer = self._renderer
        if renderer is None:
            return
        running = replace(job, state=PhotoState.RUNNING, started_at=self._clock())
        self._store.save(running)
        try:
            upscaled = renderer.render(
                source=self._store.path(job.run_id, job.id, "source"),
                raw=self._store.path(job.run_id, job.id, "raw"),
                photo=self._store.path(job.run_id, job.id, "photo"),
                prompt=build_prompt(job.options),
                size=(job.width, job.height),
            )
            done = replace(
                running, state=PhotoState.SUCCEEDED, finished_at=self._clock(), upscaled=upscaled
            )
        except Exception as error:  # noqa: BLE001 - любая ошибка задания - это его итог, а не падение очереди
            done = replace(
                running,
                state=PhotoState.FAILED,
                finished_at=self._clock(),
                error=str(error) or type(error).__name__,
            )
        self._store.save(done)
        with self._guard:
            self._active.discard(job.id)


def species_names(names: Sequence[str]) -> tuple[str, ...]:
    """Названия видов из запроса: без повторов, пустых и чересчур длинных строк."""
    seen: list[str] = []
    for raw in names:
        name = " ".join(raw.split())[:60]
        if name and name not in seen:
            seen.append(name)
    return tuple(seen[:MAX_SPECIES])
