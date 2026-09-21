"""Демонстрационный участок для кнопки «показать сразу».

Это фрагмент настоящего чертежа улицы Берзарина из пилотного проекта: подлинные имена
слоёв Мосгеотреста, настоящие подземные сети с подписанными диаметрами, борт, газоны,
ограды, опоры и застройка. Синтетический топоплан, нарисованный кодом, тут не годился:
на нём не видно ни настоящей плотности сетей, ни того, что сервис разбирает чужие
конвенции именования слоёв, - а это и есть половина задачи.

Фрагмент лежит внутри пакета, а не в датасете: на стенде жюри датасета нет, а показывать
сервис надо с первого клика. Происхождение и способ пересборки - `samples/README.md`.
"""

from __future__ import annotations

import shutil
from pathlib import Path

SAMPLE_DIR = Path(__file__).resolve().parent / "samples"
SAMPLE_FILE = SAMPLE_DIR / "berzarina_fragment.dxf"
SAMPLE_NAME = "улица Берзарина - фрагмент.dxf"


def write_sample(path: Path) -> Path:
    """Положить демонстрационный чертёж по указанному пути и вернуть его."""
    if not SAMPLE_FILE.exists():
        message = (
            f"Демонстрационный участок не найден: {SAMPLE_FILE}. Он поставляется вместе с "
            "пакетом; пересобрать - tools/make_demo_fragment.py."
        )
        raise FileNotFoundError(message)
    path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(SAMPLE_FILE, path)
    return path
