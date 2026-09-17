"""Проставить видам каталога категории насаждений из табл. В.6 МГСН 1.02-02.

Значения ячеек взяты из текста meganorm.ru (https://meganorm.ru/Data2/1/4294845/4294845750.htm,
приложение В, табл. В.6). Таблица сохранилась в редакции от 24.05.2022 (PDF на knd.mos.ru),
но отметки по ячейкам в PDF при переводе в текст теряют строки, поэтому по ней сверены только
заголовок и порядок видов.

Перевод отметок: «+» - plus; «+ с огр.», «огр.», «бульв. с огр.», «только ул.», «маг с огр.» -
limited; «-» - minus; пустая ячейка - категория не записывается. «Только ул.» отнесено к
limited, потому что улицу от магистрали сервис не отличает.

Скрипт идемпотентен: запись с полем categories пропускается.

    uv run python tools/research/apply_mgsn_b6.py
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CATALOG = ROOT / "config" / "species.yaml"
ORDER = ("parks", "squares", "streets", "yards", "special")
P, L, M, N = "plus", "limited", "minus", None
# код вида -> (строка таблицы В.6, отметки в порядке ORDER)
TABLE: dict[str, tuple[str, tuple[str | None, ...]]] = {
    "picea_pungens": ("Ель колючая", (P, P, M, M, P)),
    "thuja_occidentalis": ("Туя западная", (P, P, L, P, P)),
    "betula_pendula": ("Береза повислая", (P, P, L, P, P)),
    "crataegus_laevigata": ("Боярышник колючий", (P, P, P, P, P)),
    "ulmus_laevis": ("Вяз гладкий", (P, P, P, P, P)),
    "ulmus_pumila": ("Вяз приземистый", (P, P, M, P, P)),
    "quercus_robur": ("Дуб черешчатый", (P, P, M, L, P)),
    "salix_alba_tristis": ("Ива белая", (P, L, L, P, P)),
    "acer_ginnala": ("Клен Гиннала", (P, P, L, P, P)),
    "acer_platanoides": ("Клен остролистный и его формы", (P, L, L, P, P)),
    "acer_saccharinum": ("Клен серебристый", (P, L, M, P, P)),
    "aesculus_hippocastanum": ("Конский каштан обыкновенный", (P, L, L, P, P)),
    "tilia_cordata": ("Липа мелколистная", (P, L, L, P, P)),
    "tilia_platyphyllos": ("Липа крупнолистная", (P, L, L, P, P)),
    "elaeagnus_angustifolia": ("Лох узколистный", (P, L, M, P, P)),
    "sorbus_aucuparia": ("Рябина обыкновенная", (P, L, L, P, P)),
    "populus_balsamifera": ("Тополь бальзамический", (M, L, L, P, L)),
    "populus_simonii": ("Тополь китайский", (P, L, L, P, P)),
    "prunus_maackii": ("Черемуха Маака", (P, L, M, P, P)),
    "prunus_padus": ("Черемуха обыкновенная", (P, P, M, L, L)),
    "malus_niedzwetzkyana": ("Яблоня Недзведского", (P, P, M, M, M)),
    "malus_decorative": ("Яблоня ягодная", (P, P, M, M, M)),
    "fraxinus_excelsior": ("Ясень обыкновенный", (P, P, L, P, P)),
    "cornus_alba": ("Дерен белый", (P, P, M, P, P)),
    "lonicera_tatarica": ("Жимолость (различные виды)", (P, L, L, P, P)),
    "amelanchier_spicata": ("Ирга (различные виды)", (P, L, M, P, P)),
    "cotoneaster_lucidus": ("Кизильник блестящий", (P, P, P, P, P)),
    "physocarpus_opulifolius": ("Пузыреплодник калинолистный", (N, N, N, P, P)),
    "syringa_josikaea": ("Сирень венгерская", (P, L, L, P, P)),
    "syringa_vulgaris": ("Сирень обыкновенная", (P, L, L, P, P)),
    "spiraea_vanhouttei": ("Спирея (различные виды)", (P, P, L, P, P)),
    "spiraea_cinerea": ("Спирея (различные виды)", (P, P, L, P, P)),
    "spiraea_japonica": ("Спирея (различные виды)", (P, P, L, P, P)),
    "spiraea_betulifolia": ("Спирея (различные виды)", (P, P, L, P, P)),
    "forsythia_ovata": ("Форзиция", (P, L, L, P, P)),
    "philadelphus_coronarius": ("Чубушник венечный", (P, L, M, P, P)),
}


def main() -> None:
    text = CATALOG.read_text(encoding="utf-8")
    applied = 0
    for code, (row, marks) in TABLE.items():
        entry = re.search(rf"- \{{code: {code},.*?\n     sources: \{{", text, flags=re.DOTALL)
        if entry is None:
            raise SystemExit(f"вид {code} не найден в каталоге")
        if "categories:" in entry.group(0):
            continue
        pairs = ", ".join(f"{name}: {mark}" for name, mark in zip(ORDER, marks, strict=True) if mark)
        source = f'categories: "МГСН 1.02-02, прил. В, табл. В.6, строка «{row}»",\n               '
        replacement = entry.group(0)[: -len("sources: {")] + (
            f"categories: {{{pairs}}},\n     sources: {{{source}"
        )
        text = text.replace(entry.group(0), replacement, 1)
        applied += 1
    CATALOG.write_text(text, encoding="utf-8", newline="\n")
    print(f"проставлено категорий: {applied}, в таблице сопоставлено видов: {len(TABLE)}")


if __name__ == "__main__":
    main()
