"""Qwen-Image-2.1 через stable-diffusion.cpp и увеличение Real-ESRGAN.

Набор под 6 ГБ видеопамяти (docs/notes/40-scene-photos.md): генератор GGUF Q4_K_S, кодировщик
Qwen3-VL-8B IQ4_XS с зрением mmproj F16, VAE модели. Модели грузятся в видеопамять по очереди
(--offload-to-cpu), предел задаёт --max-vram. Апскейлер - отдельная программа на Vulkan, её
может не быть: тогда фото остаётся размером кадра.

Программы ищутся в каталоге моделей (bin/sd-cuda, bin/sd-vulkan, bin/esrgan), если путь не
задан явно. Модели и программы в образ не входят: это локальный инструмент для бонуса ТЗ.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from PIL import Image

from green.application.photos import PhotoError

if TYPE_CHECKING:
    from green.application.photos import PhotoPrompt

DIFFUSION = "qwen-image-2.1-Q4_K_S.gguf"
VAE = "vae/qwen_image_2.1_vae_bf16.safetensors"
LLM = "Qwen3-VL-8B-Instruct-IQ4_XS.gguf"
VISION = "mmproj-Qwen3VL-8B-Instruct-F16.gguf"
LOG_TAIL = 600
SD_DIRS = ("bin/sd-cuda", "bin/sd-vulkan")
ESRGAN_DIR = "bin/esrgan"
# Nomos8kSC (CC BY 4.0) из набора Upscayl: листва без «масла» x4plus, блочную сетку
# выхода модели сглаживает. Сравнение - docs/notes/40-scene-photos.md.
ESRGAN_MODEL = "4xNomos8kSC"


@dataclass(frozen=True, slots=True)
class SdCppPhotoRenderer:
    models_dir: Path
    sd_binary: Path | None = None
    esrgan_binary: Path | None = None
    upscaler: str = ESRGAN_MODEL
    max_vram_gb: float = 6.0
    timeout_s: int = 900

    def unavailable_reason(self) -> str | None:
        missing = [
            name for name in (DIFFUSION, VAE, LLM, VISION) if not self._model(name).is_file()
        ]
        if missing:
            return f"В {self.models_dir} нет файлов модели: {', '.join(missing)}"
        if self._sd() is None:
            return "Не найдена программа stable-diffusion.cpp (sd-cli)"
        return None

    def render(
        self, *, source: Path, raw: Path, photo: Path, prompt: PhotoPrompt, size: tuple[int, int]
    ) -> bool:
        sd = self._sd()
        if sd is None:
            raise PhotoError("Не найдена программа stable-diffusion.cpp (sd-cli)")
        width, height = size
        # Кадр из браузера - PNG с альфой. Qwen-Image-2.1 умеет прозрачность и на RGBA-входе
        # возвращает RGBA, а апскейлер с альфой пишет PNG вместо JPEG: вход сплющивается.
        flat = source.with_name("input.png")
        _to_rgb(source, flat)
        command = [
            str(sd),
            "--diffusion-model", str(self._model(DIFFUSION)),
            "--vae", str(self._model(VAE)),
            "--llm", str(self._model(LLM)),
            "--llm_vision", str(self._model(VISION)),
            "-r", str(flat),
            "-p", prompt.text,
            "-n", prompt.negative,
            "-W", str(width),
            "-H", str(height),
            "--steps", str(prompt.steps),
            "--cfg-scale", f"{prompt.cfg:g}",
            "--sampling-method", "euler",
            "--offload-to-cpu",
            "--fa",
            "--vae-tiling",
            "--max-vram", f"{self.max_vram_gb:g}",
            "--model-args", "qwen_image_2_1_prefix_cache_type=q8_0",
            "-o", str(raw),
        ]  # fmt: skip
        self._run(command, raw.with_name("render.log"), sd.parent)
        if not raw.is_file():
            raise PhotoError("Модель завершилась без картинки: см. render.log задания")
        _to_rgb(raw, raw)
        esrgan = self._esrgan()
        if esrgan is None:
            return False
        upscale = [
            str(esrgan),
            "-i", str(raw),
            "-o", str(photo),
            "-n", self.upscaler,
            "-f", "jpg",
            "-m", str(esrgan.parent / "models"),
            "-t", "256",
        ]  # fmt: skip
        self._run(upscale, raw.with_name("upscale.log"), esrgan.parent)
        return photo.is_file()

    def _run(self, command: list[str], log: Path, cwd: Path) -> None:
        try:
            with log.open("wb") as out:
                done = subprocess.run(  # noqa: S603 - аргументы - пути и текст промпта, не оболочка
                    command,
                    cwd=cwd,
                    stdout=out,
                    stderr=subprocess.STDOUT,
                    timeout=self.timeout_s,
                    check=False,
                )
        except subprocess.TimeoutExpired as error:
            raise PhotoError(f"Модель не уложилась в {self.timeout_s} с") from error
        if done.returncode != 0:
            tail = log.read_bytes()[-LOG_TAIL:].decode("utf-8", errors="replace").strip()
            name = Path(command[0]).name
            raise PhotoError(f"{name} завершился с кодом {done.returncode}: {tail}")

    def _model(self, name: str) -> Path:
        return self.models_dir / name

    def _sd(self) -> Path | None:
        return self.sd_binary or _find(self.models_dir, SD_DIRS, "sd-cli")

    def _esrgan(self) -> Path | None:
        return self.esrgan_binary or _find(self.models_dir, (ESRGAN_DIR,), "realesrgan-ncnn-vulkan")


def _to_rgb(source: Path, target: Path) -> None:
    """PNG без альфы: прозрачное - на белом, как у кодировщика Qwen3-VL."""
    try:
        with Image.open(source) as image:
            if image.mode == "RGB" and source == target:
                return
            rgba = image.convert("RGBA")
    except OSError as error:
        raise PhotoError(f"Картинка {source.name} не читается: {error}") from error
    flat = Image.new("RGB", rgba.size, (255, 255, 255))
    flat.paste(rgba, mask=rgba.getchannel("A"))
    flat.save(target, format="PNG")


def _find(root: Path, folders: tuple[str, ...], name: str) -> Path | None:
    for folder in folders:
        for candidate in (root / folder / name, root / folder / f"{name}.exe"):
            if candidate.is_file():
                return candidate
    found = shutil.which(name)
    return Path(found) if found else None
