"""Набор для фото по кадру 3D-вида: модели Qwen-Image-2.1 под 6 ГБ видеопамяти и программы.

Фото - бонус и в Docker-образ не входит: без каталога моделей сервис работает полностью, кнопка
фото в 3D-виде показывает причину. Скрипт кладёт всё в раскладку, которую ищет сервис
(`infrastructure/photo/sdcpp.py`), затем сервис запускается с `GREEN_PHOTO_MODELS_DIR=<dest>`.

    uv run python tools/photos/fetch_models.py --dest ~/green-models --platform linux
    uv run python tools/photos/fetch_models.py --dest D:/models/qwen --platform windows
    uv run python tools/photos/fetch_models.py --dest /tmp/x --check     # только ссылки

Около 10,5 ГБ. Уже скачанный файл того же размера пропускается, так что прерванную загрузку
можно повторить. Подробности и замеры - docs/notes/40-scene-photos.md.
"""

# ruff: noqa: INP001, T201 - инструмент установки набора для фото

from __future__ import annotations

import argparse
import shutil
import stat
import sys
import urllib.request
import zipfile
from pathlib import Path

HF = "https://huggingface.co"
SD = "https://github.com/leejet/stable-diffusion.cpp/releases/download/master-929-3f8527a"
ESRGAN = "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0"
NOMOS = "https://raw.githubusercontent.com/upscayl/custom-models/main/models"

MODELS = (
    (
        f"{HF}/unsloth/Qwen-Image-2.1-GGUF/resolve/main/qwen-image-2.1-Q4_K_S.gguf",
        "qwen-image-2.1-Q4_K_S.gguf",
    ),
    (
        f"{HF}/Comfy-Org/Qwen-Image-2.1/resolve/main/vae/qwen_image_2.1_vae_bf16.safetensors",
        "vae/qwen_image_2.1_vae_bf16.safetensors",
    ),
    (
        f"{HF}/unsloth/Qwen3-VL-8B-Instruct-GGUF/resolve/main/Qwen3-VL-8B-Instruct-IQ4_XS.gguf",
        "Qwen3-VL-8B-Instruct-IQ4_XS.gguf",
    ),
    (
        f"{HF}/Qwen/Qwen3-VL-8B-Instruct-GGUF/resolve/main/mmproj-Qwen3VL-8B-Instruct-F16.gguf",
        "mmproj-Qwen3VL-8B-Instruct-F16.gguf",
    ),
    (f"{NOMOS}/4xNomos8kSC.bin", "bin/esrgan/models/4xNomos8kSC.bin"),
    (f"{NOMOS}/4xNomos8kSC.param", "bin/esrgan/models/4xNomos8kSC.param"),
)

# Архив программы -> каталог, где сервис её ищет, и имя исполняемого файла.
PROGRAMS = {
    "linux": (
        (
            f"{SD}/sd-master-3f8527a-bin-Linux-Ubuntu-24.04-x86_64-vulkan.zip",
            "bin/sd-vulkan",
            "sd-cli",
        ),
        (
            f"{ESRGAN}/realesrgan-ncnn-vulkan-20220424-ubuntu.zip",
            "bin/esrgan",
            "realesrgan-ncnn-vulkan",
        ),
    ),
    "windows": (
        (f"{SD}/sd-master-3f8527a-bin-win-cuda12-x64.zip", "bin/sd-cuda", "sd-cli"),
        (f"{SD}/cudart-sd-bin-win-cu12-x64.zip", "bin/sd-cuda", "cudart64_12"),
        (
            f"{ESRGAN}/realesrgan-ncnn-vulkan-20220424-windows.zip",
            "bin/esrgan",
            "realesrgan-ncnn-vulkan",
        ),
    ),
}

CHUNK = 1 << 20


def remote_size(url: str) -> int | None:
    request = urllib.request.Request(url, method="HEAD")  # noqa: S310 - адреса заданы выше
    with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310
        length = response.headers.get("Content-Length")
    return int(length) if length else None


def download(url: str, target: Path) -> None:
    size = remote_size(url)
    if target.is_file() and size is not None and target.stat().st_size == size:
        print(f"есть      {target}")
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".part")
    done = 0
    with urllib.request.urlopen(url, timeout=60) as response, partial.open("wb") as out:  # noqa: S310
        while chunk := response.read(CHUNK):
            out.write(chunk)
            done += len(chunk)
            if size:
                print(f"\r{done * 100 // size:3d}%  {target.name}", end="", flush=True)
    partial.replace(target)
    print(f"\rскачан   {target}")


def unpack(archive: Path, folder: Path, program: str) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as zf:
        zf.extractall(folder)
    archive.unlink()
    if not program:
        return
    # Архивы бывают с вложенной папкой: исполняемый файл поднимается в каталог, где его ищет сервис.
    found = next((p for p in folder.rglob("*") if p.stem == program and p.is_file()), None)
    if found is None:
        sys.exit(f"В архиве {archive.name} нет программы {program}")
    if found.parent != folder:
        for item in found.parent.iterdir():
            shutil.move(str(item), folder / item.name)
    exe = folder / found.name
    exe.chmod(exe.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    print(f"программа {exe}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--dest", type=Path, required=True, help="каталог моделей (GREEN_PHOTO_MODELS_DIR)"
    )
    parser.add_argument("--platform", choices=sorted(PROGRAMS), default="linux")
    parser.add_argument("--check", action="store_true", help="только проверить ссылки")
    parser.add_argument(
        "--programs-only", action="store_true", help="без моделей Qwen, только программы"
    )
    args = parser.parse_args()
    dest = args.dest.expanduser().resolve()
    programs = PROGRAMS[args.platform]

    if args.check:
        failed = 0
        for url in [u for u, _ in MODELS] + [u for u, _, _ in programs]:
            try:
                size = remote_size(url)
                print(f"ok  {size / 1e9 if size else 0:6.2f} ГБ  {url}")
            except OSError as error:
                failed += 1
                print(f"нет {url}: {error}")
        sys.exit(1 if failed else 0)

    # Сначала программы: архив апскейлера несёт свою папку models, модель ложится поверх.
    for url, rel, program in programs:
        folder = dest / rel
        if program and any(p.stem == program for p in folder.glob(f"{program}*")):
            print(f"есть      {folder / program}")
            continue
        archive = dest / "bin" / url.rsplit("/", 1)[1]
        download(url, archive)
        unpack(archive, dest / rel, program)
    for url, rel in MODELS:
        if args.programs_only and not rel.startswith("bin/"):
            continue
        download(url, dest / rel)
    print(f"\nГотово. Запуск сервиса с фото: GREEN_PHOTO_MODELS_DIR={dest} uv run green serve")


if __name__ == "__main__":
    main()
