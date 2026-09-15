"""Извлекает одну улицу из «Пилотный проект 20 улиц.zip» без фото и видео."""

import argparse
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ZIP = ROOT / "dataset" / "Датасет" / "Пилотный проект 20 улиц.zip"
OUT = ROOT / "data" / "streets"
SKIP_EXT = (".jpg", ".jpeg", ".heic", ".png", ".mp4")


def entry_name(info: zipfile.ZipInfo) -> str:
    if info.flag_bits & 0x800:
        return info.filename
    try:
        return info.filename.encode("cp437").decode("cp866")
    except UnicodeError:
        return info.filename


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("street", help='префикс папки улицы, например "16. улица Берзарина"')
    ap.add_argument("--with-media", action="store_true")
    args = ap.parse_args()

    prefix = f"Пилотный проект 20 улиц/{args.street}"
    n = 0
    with zipfile.ZipFile(ZIP) as z:
        for info in z.infolist():
            name = entry_name(info)
            if not name.startswith(prefix) or name.endswith("/"):
                continue
            if not args.with_media and name.lower().endswith(SKIP_EXT):
                continue
            dst = OUT / name
            dst.parent.mkdir(parents=True, exist_ok=True)
            with z.open(info) as src, dst.open("wb") as f:
                while chunk := src.read(1 << 20):
                    f.write(chunk)
            n += 1
    print(f"extracted {n} files -> {OUT / prefix}")


if __name__ == "__main__":
    main()
