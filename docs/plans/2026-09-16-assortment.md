# Подбор ассортимента (assortment) — спецификация и план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** после расстановки посадок назначить каждой из них вид растения так, чтобы вид проходил нормы и условия площадки, план не был монокультурой, а у каждой посадки было обоснование «почему этот вид здесь» со ссылками на источник и список альтернатив с оценкой.

**Architecture:** отдельный проход `assort` в `PlanSite.execute` между `place` и `explain`; чистый модуль `green.application.assortment` (без фреймворков, как требует import-linter); база видов `config/species.yaml` v2 с источником и статусом у каждого поля; жёсткие фильтры считаются по уже измеренным расстояниям из `Placement.checks`; назначение видов — целочисленная задача (scipy `milp`, HiGHS) с квотами разнообразия и однородностью рядов, жадный запасной путь; вывод в `plan.json`, `assortment.json`, объяснения и `interpretations.csv`.

**Tech Stack:** Python 3.14, dataclasses (домен), pydantic (только в `infrastructure/config`), numpy, scipy.optimize.milp (уже в зависимостях), pytest, ruff ALL, ty, import-linter.

**Spec:** раздел «Спецификация» этого файла; общий контекст — `docs/spec.md` (стадия 5 «Генерация: породы после позиций»), `docs/algorithm.md` (текущий конвейер), ТЗ `ТЗ/tz_dpioos_2026.txt` п. 2.2–2.4, 2.8.

## Global Constraints

- Python ≥ 3.14, uv ≥ 0.12.15; `uv run ruff check src tests`, `uv run ruff format --check src tests`, `uv run ty check src`, `uv run lint-imports`, `uv run pytest` — всё зелёное перед каждым коммитом.
- `green.domain` и `green.application` не импортируют ezdxf, pydantic, yaml, orjson, structlog, fastapi (контракт import-linter). scipy/numpy/shapely можно.
- Ветка `feat/assortment` от `origin/main`; conventional commits на английском (`feat(assortment): …`, `test: …`, `docs: …`); PR в `main`.
- Каждый факт о виде в базе несёт `sources` и `status` (`verified` — сверен с актом/справочником, `reference` — из справочника без сверки, `pilot` — из паспортов пилота, `draft`). Объяснение обязано различать норму (акт и пункт), рекомендацию (справочник) и эмпирику пилота — эвристику нельзя выдавать за норму.
- Ничего не меняется в исходных слоях DXF; `verify.ok` остаётся `true` (проверяется существующим тестом сквозного прогона).
- Результат детерминирован: одинаковый вход и профиль дают одинаковое назначение (порядок обхода фиксирован, солвер без случайности).

---

## Спецификация

### 1. Зачем

Сейчас профиль задаёт один вид на весь прогон (`species_code`), и объяснение посадки не отвечает на вопрос «почему липа». ТЗ (п. 2.2–2.3) требует учитывать «климатические и типовые условия посадки (по доступным справочникам)» и рекомендовать «типовые посадки», п. 2.8 — обоснование каждого решения со ссылкой на акт и пункт. Часть норм зависит от вида: 369-ПП (инвазивные), 743-ПП п. 3.6.18 (женские тополя, засоряющие и аллергенные растения), МГСН 1.02-02 п. 4.2.8 (отступ от теплосети по роду), прим. к табл. 9.1 СП 42.13330.2016 (кроны более 5 м), охранная зона ВЛ (высота). Без подбора вида эти нормы проверить нельзя.

### 2. Как делают другие (что берём)

- **Citree** (TU Dresden, 350+ видов): пользователь описывает площадку, критерии делятся на обязательные (вид, не прошедший, в список не попадает) и диапазонные, результат ранжируется по степени соответствия. Берём двухступенчатость «фильтр → ранжирование» и подсветку, какие критерии прошли.
- **Обзоры MCDA-подходов** (Landscape and Urban Planning, Urban Forestry & Urban Greening): чаще всего применяются фильтрация по правилам плюс взвешенная матрица критериев; группы критериев — региональная адаптация, городская среда, эстетика, уход, рост. Берём группы факторов и взвешенную сумму с весами в профиле; AHP/TOPSIS не берём (для ~10 критериев не дают преимущества, зато усложняют объяснение).
- **Правило 10-20-30** (Santamour, 1990): не больше 10% одного вида, 20% рода, 30% семейства — защита от потери насаждений от вредителя или болезни. Берём как квоты по умолчанию, настраиваемые в профиле; считаем вместе с существующими деревьями.
- **Теодоронский, «Рекомендации по нормативной плотности и видовому составу»**: плотность 100–125 деревьев/га в жилых районах, 150–160 на бульварах, 100–130 в скверах; дополнительный ассортимент 10–15%, интродуценты не более 5–7%. Плотность — не наша задача (передаётся в размещение, см. «Смежные задачи»), доли ассортимента — как мягкие цели.

Чего у других нет и что даёт нам преимущество: нормативная трассировка каждого фактора (акт, пункт), эмпирика пилота (78 видов из паспортов семи улиц с текстами «особые характеристики»), назначение с квотами как единая задача оптимизации вместо ручного перебора.

### 3. Данные

`config/species.yaml` v2 — одна запись на вид/сорт. Поля (все с источником в `sources` по имени поля и общим `status`):

| Группа | Поля | Откуда |
|---|---|---|
| Таксономия | `code`, `name_ru`, `name_lat`, `genus`, `family` | латинское имя (род — первое слово), семейство — справочник |
| Габарит | `life_form` (tree_large ≥20 м / tree_medium 10–20 / tree_small <10 / shrub_tall / shrub_medium / shrub_low / groundcover / perennial), `height_m`, `crown_mature_m`, `crown_diameter_m` (крона через 10 лет — уже есть, для отрисовки), `root_type` (surface / tap / mixed), `growth` (slow / medium / fast), `lifespan_years` | ассортиментные ведомости пилота (диаметр кроны), справочники |
| Экология | `hardiness_zone` (USDA, Москва 4b–5a → допуск ≤ 4 по умолчанию, порог в профиле), `light` (shade / semi / sun — минимальная потребность), `moisture` (dry / mesic / wet / any), `salt_tolerance` 0–2, `gas_tolerance` 0–2, `compaction_tolerance` 0–2 | справочники; тексты «особые характеристики» паспортов дают частичные признаки (пыле-, газоустойчив, теневынослив) |
| Ограничения | `allergen` 0–2, `toxic`, `thorny`, `fluff` (пух), `fruit_litter`, `invasive_group` (группа по 369-ПП или null) | 369-ПП, 743-ПП п. 3.6.18, справочники |
| Декоративность | `decor_months` (список месяцев пика), `evergreen` | паспорта («Пиковая декоративность») |
| Применение | `uses` (row / group / solitaire / hedge / under_lines / grate), `care_level` 1–3 | паспорта («функционально-декоративные задачи», карта ухода), практика |
| Эмпирика | `pilot_streets` (в скольких паспортах пилота встречается), `pilot_count` (суммарное количество) | `dataset/catalog/species_from_passports.csv` |

YAML, а не SQLite: 60–100 записей, правки видны в git-диффе, эксперт ДПиООС может проверить файл глазами, схема валидируется pydantic так же, как `rules.yaml`. Импорт чужого каталога (ТЗ обещает «каталоги типовых посадок») — отдельный скрипт-конвертер в тот же YAML.

### 4. Контекст точки

Из `Placement.checks` (уже посчитано при размещении) — минимальное измеренное расстояние по каждому классу объектов: до проезжей части и борта (зона реагентов), до зданий (зона «у жилья» для 743-ПП п. 3.6.18 и габарит кроны), до теплосети (правила по роду), до ВЛ (исход правила R-OHL: под линией или нет), до существующих деревьев. Плюс структура, к которой относится точка (ряд, группа, одиночка) и соседи. Тени и инсоляции в v1 нет (см. «Смежные задачи»: этажность зданий из подписей топоплана).

### 5. Жёсткие фильтры (вид отбрасывается в точке)

| Фильтр | Вид причины | Источник в объяснении |
|---|---|---|
| Запрет вида (инвазивные) | норма | `species_bans` из `rules.yaml` (369-ПП) — уже есть, `RuleBook.ban_for` |
| Правила отступов по роду (теплосеть: липа/клён 2 м, берёза/тополь 4 м) | норма | `RuleBook.distance_rules_for(тип, name_lat)` — правила с `genera`, сравнение с измеренным расстоянием класса |
| Крона более 5 м увеличивает отступы табл. 9.1 | норма + проектный параметр | прим. к табл. 9.1 СП 42.13330.2016; величина увеличения проектная (0,5 м на каждый метр кроны сверх 5 м, параметр `crown_extra_per_m`) |
| Под воздушной линией только низкорослые (высота ≤ `max_height_under_lines_m`, по умолчанию 4 м) | норма + проектный параметр | ПП РФ N 160 п. 10 «в» (правило R-OHL), высота — проектный порог |
| Пух и сильные аллергены ближе `housing_zone_m` (30 м) от зданий | норма | 743-ПП п. 3.6.18 |
| Зона морозостойкости вида выше региональной | справочник | USDA-зоны, порог региона в профиле (`region_hardiness_zone`, Москва 4) |
| Нет солеустойчивости в `salt_zone_m` (5 м) от проезжей части или борта | справочник | практика реагентов (паспорта пилота: «устойчивы к реагентам»), справочники |
| Заданный ассортимент (режим `given`): виды вне списка | параметр участка | профиль |

Если для точки не прошёл ни один вид, посадка остаётся с видом по умолчанию профиля и получает пометку `no_species` в объяснении и в сводке — ничего не скрывается.

### 6. Оценка пригодности (0–100)

Взвешенная сумма факторов в [0, 1], веса в профиле (`assortment_weights`, сумма нормируется):

| Фактор | Что считает | Вес по умолчанию |
|---|---|---|
| `site` | соль и газ у проезжей части (по `salt_tolerance`, `gas_tolerance`, если точка в `salt_zone_m`), уплотнение (`compaction_tolerance`) | 0.30 |
| `function` | соответствие структуре: `row` для рядов, `group` для групп, `solitaire` для одиночек, `under_lines` под ВЛ | 0.20 |
| `decor` | доля месяцев пика декоративности, бонус вечнозелёным | 0.15 |
| `longevity` | `lifespan_years` / 150, не больше 1 | 0.15 |
| `care` | 1 для `care_level` 1, 0.5 для 2, 0 для 3 | 0.10 |
| `pilot` | `pilot_streets` / 7 — заменитель наличия в питомниках и проверенности в Москве | 0.10 |

Проценты — это `round(100 × score)`, в объяснении выводятся с разбивкой по факторам, чтобы «82%» было проверяемо. Разнообразие и однородность рядов в оценку точки не входят — это ограничения и цель солвера (п. 7), иначе они двойным счётом ломают сравнение альтернатив.

### 7. Назначение

1. **Структуры.** Посадки аллеи (пометка «аллея вдоль борта») склеиваются в ряды: одиночная связь соседей ближе 1,5 шага. Посадки газона — в группы той же связью; кластер из 1–2 точек — одиночка. У ряда и группы один доминантный вид (ряд — строго один, группа — доминант плюс спутники, `group_max_species` = 3).
2. **Задача.** Переменные `x[p,s] ∈ {0,1}` только для пар, прошедших фильтр; `y[st,s] ∈ {0,1}` — вид `s` используется в структуре `st`. Ограничения: одна посадка — один вид; `x[p,s] ≤ y[st(p),s]`; для рядов `Σ_s y[st,s] = 1`, для групп `≤ group_max_species`; квоты `Σ_p x[p,s] + E_s ≤ q_species × (N + E)` по видам, аналогично по родам и семействам (`E` — существующие деревья из перечётной ведомости, если подана); доля хвойных в `[conifer_share_min, conifer_share_max]`; в режиме `given` — `Σ_p x[p,s] = count_s`. Цель: максимум `Σ score[p,s] x[p,s] − λ Σ y[st,s]` (штраф за пестроту, `λ = 0.3`). Решатель `scipy.optimize.milp` (HiGHS), лимит времени 60 с; при неуспехе — жадный обход структур по убыванию размера с теми же квотами, факт фоллбэка попадает в предупреждения.
3. **Альтернативы.** Для каждой посадки хранятся три лучших допустимых вида по оценке с причинами — данные для будущего редактора («ель 80, сосна 69, поменять руками»).

### 8. Выход и объяснение

- `plan.json`: у посадки блок `assortment` — `score`, `factors`, `structure {kind, id}`, `reasons` (норма / справочник / пилот), `alternatives` (код, имя, оценка, причина уступки), `status` (`assigned` / `no_species` / `given`).
- `assortment.json`: счётчики по видам, родам, семействам с долями и квотами; доля хвойных; индекс Шеннона; покрытие декоративности по месяцам; список нарушений квот (если солвер не смог); число `no_species`; учтённая существующая популяция; режим и веса.
- `interpretations.csv/json`: строки правил по виду (запрет, правило по роду, крона, ВЛ) — те же колонки, что у отступов, с `rule_id` и актом.
- Текст объяснения посадки дополняется: «Вид: липа мелколистная (82%): солеустойчива при 2,4 м до проезжей части (справочник); теплосеть 2,6 м при норме 2,0 м для рода Tilia (R-HEAT-TILIA-001: МГСН 1.02-02 п. 4.2.8); не инвазивна (369-ПП); ряд из 9 деревьев одного вида; доля вида 9% при квоте 10%. Альтернативы: клён остролистный 74%, рябина 61%».
- DXF: блок и атрибут SPECIES уже пишутся из `placement.species` — ничего менять не нужно.

### 9. Что осознанно не делаем в этой версии («Смежные задачи»)

- Тень и инсоляция по этажности зданий (подписи вида «9КЖ» на топоплане) — отдельная задача после проверки подписей на данных.
- Класс «детская площадка» для запрета ядовитых и колючих — нужен новый `ObjectClass` и правила классификатора (изменение ядра, согласовать с Кириллом).
- Позиции существующих деревьев с породами (привязка номеров перечётки к дендроплану) — в v1 только счётчики по породам для квот.
- Кустарники, живые изгороди, покрытия и травосмеси как отдельные слои плана — следующий план; схема базы их уже вмещает (`life_form`, `uses`).
- Плотность посадок на гектар (Теодоронский, МГСН) — параметр размещения, а не подбора; передать Кириллу как `max_trees_per_ha` для сетки по газону.
- Автогенерация паспорта объекта и ведомости посадочного материала из выбранного ассортимента — следующий план (шаблоны есть в датасете у семи улиц).
- Обучение весов по планам проектировщиков — после того, как появятся метрики сравнения.

### 10. Открытые вопросы к организаторам

Есть ли обещанные ТЗ «каталоги типовых посадок с нормами по отступам и условиям посадки» и «наборы параметров для тестовых участков» — если да, конвертер в наш YAML и режим `given` под их формат. Полные тексты приложений 515-ПП (базовый ассортимент) и 369-ПП (перечень инвазивных по группам).

---

## Структура файлов

| Файл | Ответственность |
|---|---|
| `src/green/domain/planting.py` (modify) | `Species` расширяется полями базы с значениями по умолчанию; `LifeForm`; `AssortmentInfo`; `Placement.assortment`; `Plan.assortment_summary` |
| `src/green/infrastructure/config/schemas.py` (modify) | `SpeciesModel` v2, `ProfileModel` — параметры подбора |
| `src/green/infrastructure/config/repositories.py` (modify) | `YamlSpeciesCatalog` → домен со всеми полями |
| `src/green/application/params.py` (modify) | параметры подбора в `PlanParams` |
| `src/green/application/assortment/__init__.py` (create) | `assign_species` — публичная функция прохода |
| `src/green/application/assortment/context.py` (create) | `SiteContext` из `Placement.checks` |
| `src/green/application/assortment/structures.py` (create) | ряды, группы, одиночки |
| `src/green/application/assortment/filters.py` (create) | жёсткие фильтры → `Reason` |
| `src/green/application/assortment/scoring.py` (create) | факторы и оценка |
| `src/green/application/assortment/assign.py` (create) | MILP и жадный запасной путь |
| `src/green/application/assortment/summary.py` (create) | сводка: доли, квоты, Шеннон, сезонность |
| `src/green/application/use_case.py` (modify, строки 98–101) | стадия `assort` между `place` и `explain` |
| `src/green/application/explain.py` (modify) | фраза о виде и альтернативах |
| `src/green/infrastructure/reports/artifacts.py` (modify) | `assortment` в `plan.json`, файл `assortment.json`, строки видов в `interpretations` |
| `src/green/infrastructure/inventory.py` (create) | перечётная ведомость → счётчики существующих пород |
| `src/green/interfaces/cli/main.py` (modify) | `--inventory` |
| `config/species.yaml` (rewrite, v2) | база видов |
| `config/profiles/*.yaml` (modify) | параметры подбора |
| `tools/build_species_catalog.py` (create) | черновик записей из `dataset/catalog/species_from_passports.csv` |
| `docs/species.md` (create), `docs/algorithm.md` (modify), `README.md`, `CLAUDE.md` (modify) | документация |
| `tests/test_species_catalog.py`, `tests/test_assortment_context.py`, `tests/test_assortment_filters.py`, `tests/test_assortment_scoring.py`, `tests/test_assortment_structures.py`, `tests/test_assortment_assign.py`, `tests/test_assortment_pipeline.py`, `tests/test_inventory.py` (create) | тесты |

Точки подключения, без которых модуль не заработает: `use_case.py` (стадия), `container.py` (каталог уже передаётся как `species`, новых зависимостей нет), `repositories.py` (`PlanParams(**values)` строится по именам полей — новые поля `PlanParams` и `ProfileModel` должны совпадать), `artifacts.py` (иначе результат невидим), `tests/test_pipeline_synthetic.py` (сквозной тест начнёт назначать разные виды — проверить, что его ожидания не завязаны на липу).

---

### Task 1: База видов — схема, домен, загрузка

**Files:**
- Modify: `src/green/domain/planting.py` (класс `Species`, строки 31–36)
- Modify: `src/green/infrastructure/config/schemas.py` (`SpeciesModel`, строки 90–99)
- Modify: `src/green/infrastructure/config/repositories.py` (`YamlSpeciesCatalog.all`, строки 136–151)
- Rewrite: `config/species.yaml`
- Test: `tests/test_species_catalog.py`

**Interfaces:**
- Produces: `Species` с полями из спецификации §3 (все новые поля со значениями по умолчанию, старые вызовы `Species(code, name_ru, name_lat, crown_diameter_m)` продолжают работать); `LifeForm(StrEnum)`; `Species.is_conifer` (семейство Pinaceae или Cupressaceae); `SpeciesCatalog.all()` возвращает полные записи.

- [ ] **Step 1: Тест схемы и загрузки**

```python
# tests/test_species_catalog.py
from __future__ import annotations

from pathlib import Path

import pytest

from green.application.errors import ConfigurationError
from green.domain.norms import genus_of
from green.domain.planting import LifeForm
from green.infrastructure.config.repositories import YamlSpeciesCatalog

ROOT = Path(__file__).resolve().parents[1]
CATALOG = YamlSpeciesCatalog(ROOT / "config" / "species.yaml")


def test_catalog_entries_are_complete_and_consistent() -> None:
    species = CATALOG.all()
    assert len(species) >= 40
    codes = [s.code for s in species]
    assert len(codes) == len(set(codes))
    for s in species:
        assert s.genus == genus_of(s.name_lat), s.code
        assert s.family, s.code
        assert s.height_m > 0 and s.crown_mature_m > 0, s.code
        assert 1 <= s.hardiness_zone <= 9, s.code
        assert s.decor_months <= set(range(1, 13)), s.code
        assert s.status in {"verified", "reference", "pilot", "draft"}, s.code
        assert set(s.sources) >= {"hardiness_zone", "salt_tolerance"}, s.code


def test_invasive_species_carry_group_and_are_banned() -> None:
    negundo = CATALOG.get("acer_negundo")
    assert negundo.invasive_group is not None


def test_conifers_detected_by_family() -> None:
    assert CATALOG.get("picea_abies").is_conifer
    assert not CATALOG.get("tilia_cordata").is_conifer
    assert CATALOG.get("picea_abies").life_form is LifeForm.TREE_LARGE


def test_missing_field_is_rejected(tmp_path: Path) -> None:
    (tmp_path / "species.yaml").write_text(
        "version: 2\nspecies:\n  - {code: x, name_ru: X, name_lat: Xus x, crown_diameter_m: 3}\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigurationError):
        YamlSpeciesCatalog(tmp_path / "species.yaml").all()
```

- [ ] **Step 2: Запустить, убедиться, что падает**

Run: `uv run pytest tests/test_species_catalog.py -v`
Expected: FAIL (`LifeForm` не импортируется, поля отсутствуют).

- [ ] **Step 3: Домен**

В `src/green/domain/planting.py` перед `Species`:

```python
class LifeForm(StrEnum):
    TREE_LARGE = "tree_large"  # взрослая высота 20 м и выше
    TREE_MEDIUM = "tree_medium"  # 10-20 м
    TREE_SMALL = "tree_small"  # до 10 м
    SHRUB_TALL = "shrub_tall"  # выше 2 м
    SHRUB_MEDIUM = "shrub_medium"  # 1-2 м
    SHRUB_LOW = "shrub_low"  # ниже 1 м
    GROUNDCOVER = "groundcover"
    PERENNIAL = "perennial"


CONIFER_FAMILIES = frozenset({"Pinaceae", "Cupressaceae", "Taxaceae"})
```

`Species` — оставить четыре существующих поля первыми, дальше поля §3 со значениями по умолчанию (`genus: str = ""`, `family: str = ""`, `life_form: LifeForm = LifeForm.TREE_MEDIUM`, `height_m: float = 0.0`, `crown_mature_m: float = 0.0`, `evergreen: bool = False`, `root_type: str = "mixed"`, `growth: str = "medium"`, `lifespan_years: int = 0`, `hardiness_zone: int = 4`, `light: str = "sun"`, `moisture: str = "mesic"`, `salt_tolerance: int = 1`, `gas_tolerance: int = 1`, `compaction_tolerance: int = 1`, `allergen: int = 0`, `toxic: bool = False`, `thorny: bool = False`, `fluff: bool = False`, `fruit_litter: bool = False`, `invasive_group: int | None = None`, `decor_months: frozenset[int] = frozenset()`, `uses: frozenset[str] = frozenset()`, `care_level: int = 1`, `pilot_streets: int = 0`, `pilot_count: int = 0`, `status: str = "draft"`, `sources: Mapping[str, str] = field(default_factory=dict)`) и свойство:

```python
    @property
    def is_conifer(self) -> bool:
        return self.family in CONIFER_FAMILIES
```

- [ ] **Step 4: Схема pydantic**

`SpeciesModel` в `schemas.py`: те же поля с ограничениями (`Field(ge=0, le=2)` для шкал 0–2, `Literal[...]` для `root_type`, `growth`, `light`, `moisture`, `status`, `decor_months: list[int]` с валидатором диапазона 1–12, `uses: list[Literal["row","group","solitaire","hedge","under_lines","grate"]]`, `sources: dict[str, str]`, `status`). Обязательные без умолчания: `genus`, `family`, `life_form`, `height_m`, `crown_mature_m`, `hardiness_zone`, `salt_tolerance`, `sources`. `SpeciesFile.version: Literal[2]`.

- [ ] **Step 5: Загрузка**

`YamlSpeciesCatalog.all` — построить `Species` из всех полей модели (`frozenset(s.decor_months)`, `frozenset(s.uses)`, `LifeForm(s.life_form)`), кэшировать результат в атрибуте после первого чтения (сейчас файл читается на каждый `get`).

- [ ] **Step 6: Перенести 12 существующих записей в v2**

`config/species.yaml`: `version: 2`, каждая запись — полный набор полей. Для `acer_negundo` — `invasive_group: 1`, `sources: {invasive_group: "369-ПП, перечень (группа сверить по тексту)"}`. Значения экологии — из справочника с `status: reference` и `sources` вида `"Колесников А.И. Декоративная дендрология, 1974"`; для видов из паспортов пилота — `pilot_streets`, `pilot_count` из `dataset/catalog/species_from_passports.csv`. Пока в тесте порог `>= 40` не пройдёт — временно 12 записей, порог поднять в Task 2.

- [ ] **Step 7: Прогнать тесты и линтеры**

Run: `uv run pytest tests/test_species_catalog.py -v && uv run pytest -q && uv run ruff check src tests && uv run ty check src && uv run lint-imports`
Expected: PASS (кроме порога 40 — оставить `>= 12` до Task 2, потом поднять).

- [ ] **Step 8: Commit**

```bash
git add src/green/domain/planting.py src/green/infrastructure/config/schemas.py src/green/infrastructure/config/repositories.py config/species.yaml tests/test_species_catalog.py
git commit -m "feat(species): catalog schema v2 with ecology, restrictions, decor and sources"
```

---

### Task 2: Наполнение базы из паспортов пилота и справочников

**Files:**
- Create: `tools/build_species_catalog.py`
- Modify: `config/species.yaml`
- Create: `docs/species.md`
- Modify: `tests/test_species_catalog.py` (порог `>= 40`)

**Interfaces:**
- Consumes: `dataset/catalog/species_from_passports.csv` (колонки `street,name,lat,height,count,traits,function,form,peak`).
- Produces: `config/species.yaml` с ≥ 40 видами; `docs/species.md` — описание полей, шкал и источников.

- [ ] **Step 1: Скрипт-черновик**

`tools/build_species_catalog.py`: читает CSV, группирует по нормализованному имени (первые два слова без сорта в кавычках), считает `pilot_streets`, `pilot_count`, извлекает `decor_months` из «Пиковая декоративность» (словарь месяцев и диапазонов «май–октябрь», «круглый год» → все 12), из «особые характеристики» — признаки по ключевым словам (`газо`, `пыле`, `реагент` → `gas_tolerance: 2`/`salt_tolerance: 2`; `тенев` → `light: shade`; `уплотн` → `compaction_tolerance: 2`; `не пылит` → `fluff: false`), высоту из «проектная высота» (см → м, верхняя граница). Печатает YAML-черновик записей с `status: draft` и `sources: {pilot_streets: "паспорта объектов пилота", ...}` для последующей ручной доводки; существующие записи не перезаписывает (сопоставление по `name_lat`). Скрипт — в `tools/`, зависимость `pandas` через `uv run --with pandas`, в пакет не входит.

- [ ] **Step 2: Ручная доводка сорока видов**

Взять 40 самых частых по `pilot_streets`, `pilot_count` (гортензия метельчатая, сосна обыкновенная, кизильник блестящий, пузыреплодник калинолистный, спирея Вангутта, клён остролистный, гортензия древовидная, липа мелколистная, яблоня Недзвецкого, клён Гиннала, тополь Симона, дерен белый, ива плакучая, спирея японская, сосна горная, клён сахаристый, дерен «Элегантиссима», можжевельник казацкий, рябинник рябинолистный, спирея серая, бересклет европейский, ель обыкновенная, ель колючая, берёза повислая, дуб черешчатый, каштан конский, черёмуха Маака, черёмуха виргинская, рябина обыкновенная, вяз гладкий, сирень венгерская, сирень обыкновенная, туя западная, псевдотсуга Мензиса, лещина обыкновенная, боярышник, лапчатка кустарниковая, вейгела, форзиция, можжевельник обыкновенный). Для каждого заполнить экологию и ограничения по справочнику (`status: reference`), таксономию (семейство), `uses` по «функционально-декоративным задачам» паспорта. Сомнительные значения — `status: draft` с пояснением в `sources`.

- [ ] **Step 3: Документация базы**

`docs/species.md`: назначение, поля и шкалы (что значит `salt_tolerance: 2`), источники и статусы, как добавить вид, как импортировать чужой каталог, известные пробелы (тексты 515-ПП и 369-ПП).

- [ ] **Step 4: Тесты**

Run: `uv run pytest tests/test_species_catalog.py -v` (порог поднят до 40)
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tools/build_species_catalog.py config/species.yaml docs/species.md tests/test_species_catalog.py
git commit -m "feat(species): seed catalog from pilot passports and references"
```

---

### Task 3: Контекст точки из проверок правил

**Files:**
- Create: `src/green/application/assortment/__init__.py` (пока пустой docstring)
- Create: `src/green/application/assortment/context.py`
- Test: `tests/test_assortment_context.py`

**Interfaces:**
- Produces:

```python
@dataclass(frozen=True, slots=True)
class SiteContext:
    placement_id: str
    x: float
    y: float
    clearance_m: Mapping[ObjectClass, float]  # минимум measured_m по классу из checks
    under_overhead_line: bool  # хотя бы одна проверка класса POWER_LINE_OVERHEAD с исходом FAIL
    structure_id: str | None = None
    structure_kind: str | None = None  # row | group | single

def site_context(placement: Placement) -> SiteContext: ...
def nearest_clearance(ctx: SiteContext, classes: Iterable[ObjectClass]) -> float | None: ...
```

- [ ] **Step 1: Тест**

```python
# tests/test_assortment_context.py
from __future__ import annotations

from green.application.assortment.context import nearest_clearance, site_context
from green.domain.norms import PlantingType
from green.domain.objects import ObjectClass
from green.domain.planting import CheckOutcome, Placement, RuleCheck, Species, Verdict


def _placement(checks: tuple[RuleCheck, ...]) -> Placement:
    return Placement(
        placement_id="p-1", number=1, planting_type=PlantingType.TREE,
        species=Species("tilia_cordata", "Липа", "Tilia cordata", 4.0),
        x=10.0, y=20.0, verdict=Verdict.ALLOWED, checks=checks,
    )


def test_context_takes_minimum_distance_per_class_and_line_flag() -> None:
    checks = (
        RuleCheck("R-ROAD-TREE-001", CheckOutcome.PASS, 2.0, 3.1, None, ObjectClass.ROAD),
        RuleCheck("R-CURB-TREE-001", CheckOutcome.PASS, 2.0, 2.4, None, ObjectClass.CURB),
        RuleCheck("R-HEAT-TREE-001", CheckOutcome.PASS, 2.0, 2.6, None, ObjectClass.UTILITY_HEAT),
        RuleCheck("R-OHL-TREE-001", CheckOutcome.FAIL, 2.0, 1.1, None, ObjectClass.POWER_LINE_OVERHEAD),
        RuleCheck("R-GAS-TREE-001", CheckOutcome.NO_DATA, 1.5, None, None, ObjectClass.UTILITY_GAS),
    )
    ctx = site_context(_placement(checks))
    assert ctx.clearance_m[ObjectClass.CURB] == 2.4
    assert ObjectClass.UTILITY_GAS not in ctx.clearance_m
    assert ctx.under_overhead_line
    assert nearest_clearance(ctx, (ObjectClass.ROAD, ObjectClass.CURB)) == 2.4
    assert nearest_clearance(ctx, (ObjectClass.BUILDING,)) is None
```

- [ ] **Step 2: Запустить — падает (модуля нет)**

- [ ] **Step 3: Реализация** — обход `placement.checks`, `clearance_m` как минимум по классу среди проверок с `measured_m is not None`; флаг линии по классу и исходу; `nearest_clearance` — минимум по переданным классам или `None`.

- [ ] **Step 4: Тест проходит, линтеры зелёные.**

- [ ] **Step 5: Commit** — `feat(assortment): site context from rule checks`

---

### Task 4: Структуры — ряды, группы, одиночки

**Files:**
- Create: `src/green/application/assortment/structures.py`
- Test: `tests/test_assortment_structures.py`

**Interfaces:**
- Consumes: `Placement.notes` (`"аллея вдоль борта"` / `"заполнение газона"` — `MODE_LABELS` из `placement.py`), `PlanParams.spacing_m`.
- Produces:

```python
@dataclass(frozen=True, slots=True)
class Structure:
    structure_id: str  # row-1, group-2, single-3
    kind: str  # row | group | single
    placement_ids: tuple[str, ...]

def build_structures(placements: Sequence[Placement], spacing_m: float) -> tuple[Structure, ...]: ...
```

- [ ] **Step 1: Тест**: 8 посадок аллеи по прямой с шагом 6 м → один `row` из 8; две кучки по 4 посадки газона на расстоянии 40 м друг от друга → две `group`; одна посадка газона в стороне → `single`; посадки аллеи с разрывом 20 м → два ряда. Проверить, что каждый `placement_id` попадает ровно в одну структуру и что `structure_id` детерминированы (повторный вызов даёт тот же результат).

- [ ] **Step 2: Реализация**: одиночная связь через `shapely.STRtree.query` по буферу `1.5 × spacing_m` внутри одного режима, объединение через union-find; порядок кластеров — по минимальному `placement_id` (детерминизм). Группа — кластер газона из 3 и более посадок, иначе `single`.

- [ ] **Step 3: Тесты и линтеры зелёные. Commit** — `feat(assortment): rows, groups and singles from placements`

---

### Task 5: Жёсткие фильтры с причинами

**Files:**
- Create: `src/green/application/assortment/filters.py`
- Modify: `src/green/application/params.py`, `src/green/infrastructure/config/schemas.py` (`ProfileModel`), `config/profiles/*.yaml`
- Test: `tests/test_assortment_filters.py`

**Interfaces:**
- Consumes: `SiteContext`, `RuleBook` (`ban_for`, `distance_rules_for(type, name_lat)`, `label_of`), `Species`.
- Produces:

```python
@dataclass(frozen=True, slots=True)
class Reason:
    kind: str  # norm | reference | pilot | composition | parameter
    text: str
    rule_id: str = ""
    source: str = ""

@dataclass(frozen=True, slots=True)
class SpeciesVerdict:
    species: Species
    allowed: bool
    reasons: tuple[Reason, ...]  # и почему прошёл, и почему нет — всё, что попадёт в объяснение

def species_verdict(species: Species, ctx: SiteContext, rulebook: RuleBook, params: PlanParams) -> SpeciesVerdict: ...
```

Параметры (добавить в `PlanParams` и `ProfileModel` с одинаковыми именами): `assortment_mode: str = "auto"` (`auto` / `given` / `single`), `given_assortment: Mapping[str, int]` (пусто), `region_hardiness_zone: int = 4`, `salt_zone_m: float = 5.0`, `housing_zone_m: float = 30.0`, `max_height_under_lines_m: float = 4.0`, `crown_extra_per_m: float = 0.5`, `quota_species: float = 0.10`, `quota_genus: float = 0.20`, `quota_family: float = 0.30`, `conifer_share: tuple[float, float] = (0.15, 0.40)`, `group_max_species: int = 3`, `structure_penalty: float = 0.3`, `assortment_weights: Mapping[str, float]` (умолчания §6). `single` сохраняет сегодняшнее поведение (все посадки — `species_code`).

- [ ] **Step 1: Тест** — по одному случаю на каждый фильтр из §5 (перечисление, каждый элемент проверяется): инвазивный (`acer_negundo` → `allowed=False`, причина `kind="norm"` с `rule_id` запрета); правило по роду (берёза при `clearance[UTILITY_HEAT]=2.6` — отброшена с `rule_id` правила рода, липа — допущена); крона более 5 м (`crown_mature_m=12` при `clearance[BUILDING]=6.0`: порог 5 + 0.5×7 = 8.5 → отброшена, причина `norm` с текстом про прим. к табл. 9.1); под ВЛ (`under_overhead_line=True`, `height_m=25` → отброшена, `height_m=3.5` — допущена); пух у жилья (`fluff=True`, `clearance[BUILDING]=12` → отброшена с источником 743-ПП п. 3.6.18; при 60 м — допущена); зона морозостойкости 6 при региональной 4 → отброшена, `kind="reference"`; соль (`salt_tolerance=0`, `clearance[CURB]=2.4` → отброшена `reference`; при 9 м — допущена); режим `given` с видом вне списка → отброшена `parameter`. И тест, что у допущенного вида в `reasons` есть положительные записи (норма по роду пройдена с числами).

- [ ] **Step 2: Реализация** — порядок проверок как в §5; текст причин на русском по шаблонам с числами (`f"теплосеть {clearance:.1f} м при норме {rule.min_distance_m:.1f} м для рода {species.genus}"`); ссылки: для правил — `rule.rule_id` и `citation_text(rule, rulebook)` из `explain.py`; для 743-ПП п. 3.6.18 — `rulebook.label_of("PP743") + ", п. 3.6.18"`; для справочных — `species.sources.get(поле, "справочник")`.

- [ ] **Step 3: Профили** — добавить параметры подбора в `strict.yaml`, `no_utilities.yaml`, `shrubs.yaml` (`assortment_mode: auto`; в `shrubs.yaml` пока `single`, пока нет слоя кустарников).

- [ ] **Step 4: Тесты, линтеры. Commit** — `feat(assortment): hard filters with normative and reference reasons`

---

### Task 6: Оценка пригодности

**Files:**
- Create: `src/green/application/assortment/scoring.py`
- Test: `tests/test_assortment_scoring.py`

**Interfaces:**
- Produces:

```python
@dataclass(frozen=True, slots=True)
class Score:
    total: float  # 0..1
    factors: Mapping[str, float]  # site, function, decor, longevity, care, pilot — каждый 0..1

def score_species(species: Species, ctx: SiteContext, params: PlanParams) -> Score: ...
def percent(score: Score) -> int: ...  # round(100 * total)
```

- [ ] **Step 1: Тест** — у проезжей части солеустойчивый вид получает `factors["site"]` выше, чем неустойчивый, вдали от дороги — одинаково; для структуры `row` вид с `uses={"row"}` получает `function` = 1, без — 0; веса нормируются (при весах, сумма которых 2, `total` тот же, что при сумме 1); `percent` округляет; вид с `decor_months` на все 12 месяцев и `evergreen` даёт `decor` = 1.

- [ ] **Step 2: Реализация** по §6.

- [ ] **Step 3: Тесты, линтеры. Commit** — `feat(assortment): weighted suitability score`

---

### Task 7: Назначение — MILP с квотами и жадный запасной путь

**Files:**
- Create: `src/green/application/assortment/assign.py`
- Test: `tests/test_assortment_assign.py`

**Interfaces:**
- Consumes: список кандидатов `Candidate(placement_id, structure_id, structure_kind, species, score)` (только прошедшие фильтр), `existing: Mapping[str, int]` (счётчики существующих по коду вида), `params`.
- Produces:

```python
@dataclass(frozen=True, slots=True)
class Assignment:
    species_by_placement: Mapping[str, str]  # placement_id -> species code
    solver: str  # "milp" | "greedy"
    quota_violations: tuple[str, ...]  # непустой, если пришлось нарушить (только у greedy)

def assign(candidates: Sequence[Candidate], structures: Sequence[Structure], catalog: Mapping[str, Species], existing: Mapping[str, int], params: PlanParams) -> Assignment: ...
```

- [ ] **Step 1: Тест** — 30 посадок в 3 рядах по 10, 5 видов, все допустимы, оценки заданы: (а) в каждом ряду один вид; (б) квота 10% при 30 посадках без существующих не даёт больше 3 одного вида, солвер сообщает `solver == "milp"` и пустые `quota_violations`; (в) с `existing={"tilia_cordata": 20}` липа не назначается ни разу; (г) режим `given` `{"picea_abies": 12, "tilia_cordata": 18}` даёт ровно такие счётчики; (д) конфигурация, где квоты невыполнимы (1 вид допустим у всех) — MILP неразрешим, `solver == "greedy"`, `quota_violations` непустой; (е) один и тот же вход дважды — одинаковый результат.

- [ ] **Step 2: Реализация** — построить разреженные матрицы для `scipy.optimize.milp` (`LinearConstraint` по каждому блоку из §7, `Bounds(0, 1)`, `integrality=1`, `options={"time_limit": 60}`); `y`-переменные только для структур из ≥ 2 посадок; при `status != 0` — жадный: структуры по убыванию размера, для каждой вид с максимальной средней оценкой, проходящий квоты, иначе лучший с записью в `quota_violations`. Индексы `p`, `s`, `st` — по отсортированным идентификаторам (детерминизм).

- [ ] **Step 3: Тесты, линтеры. Commit** — `feat(assortment): quota-constrained assignment via MILP with greedy fallback`

---

### Task 8: Проход `assort` и данные в плане

**Files:**
- Modify: `src/green/domain/planting.py` (`AssortmentInfo`, `Placement.assortment`, `Plan.assortment_summary`)
- Modify: `src/green/application/assortment/__init__.py` (`assign_species`)
- Create: `src/green/application/assortment/summary.py`
- Modify: `src/green/application/use_case.py` (стадия `assort` после `place`)
- Test: `tests/test_assortment_pipeline.py`

**Interfaces:**
- Produces:

```python
@dataclass(frozen=True, slots=True)
class Alternative:
    code: str
    name_ru: str
    percent: int
    why_not: str  # первая причина уступки: «оценка ниже», «квота рода», «ряд одного вида»

@dataclass(frozen=True, slots=True)
class AssortmentInfo:
    status: str  # assigned | given | no_species | single
    percent: int
    factors: Mapping[str, float]
    structure_id: str | None
    structure_kind: str | None
    reasons: tuple[Reason, ...]
    alternatives: tuple[Alternative, ...]

@dataclass(frozen=True, slots=True)
class AssortmentSummary:
    mode: str
    solver: str
    counts: Mapping[str, int]  # по коду вида
    genus_shares: Mapping[str, float]
    family_shares: Mapping[str, float]
    conifer_share: float
    shannon: float
    decor_by_month: Mapping[int, int]  # 1..12 -> число посадок с пиком в этом месяце
    no_species: int
    quota_violations: tuple[str, ...]
    existing: Mapping[str, int]

def assign_species(plan: Plan, rulebook: RuleBook, catalog: Sequence[Species], params: PlanParams, existing: Mapping[str, int] | None = None) -> Plan: ...
```

`Placement.assortment: AssortmentInfo | None = None`, `Plan.assortment_summary: AssortmentSummary | None = None`. В режиме `single` посадки получают `AssortmentInfo(status="single", ...)` без изменения вида.

- [ ] **Step 1: Тест** — на синтетическом плане из 40 посадок (2 ряда по 10, 2 группы по 8, 4 одиночки) с каталогом из `config/species.yaml` и `PlanParams()` по умолчанию: у каждой посадки `assortment` заполнен, `status` ∈ {assigned, no_species}, в ряду один вид, `percent` совпадает с `percent(score)` выбранного вида, альтернативы отсортированы по убыванию и не содержат выбранный вид, `assortment_summary.counts` суммируется в число назначенных, `shannon > 0`, ни один вид не превышает квоту при отсутствии нарушений; в режиме `single` виды не меняются.

- [ ] **Step 2: Реализация** — `assign_species`: структуры → контекст → для каждой посадки вердикты по всем видам каталога того же `planting_type` (деревья: `life_form` из tree_*) → кандидаты → `assign` → новые `Placement` (`dataclasses.replace(p, species=..., assortment=...)`) → `summary`. Стадия в `use_case.py`:

```python
        with watch.stage("assort"):
            plan = assign_species(plan, rulebook, self._species.all(), params)
```

- [ ] **Step 3: Сквозной синтетический тест** — в `tests/test_pipeline_synthetic.py` добавить проверку, что после прогона `strict` посадки получили `assortment` и не все виды одинаковы (при ≥ 10 посадках и квоте 10%), `verify.ok` по-прежнему `true`.

- [ ] **Step 4: Тесты, линтеры. Commit** — `feat(assortment): assign species after placement and summarize the plan`

---

### Task 9: Объяснения и артефакты

**Files:**
- Modify: `src/green/application/explain.py` (`_placement`)
- Modify: `src/green/infrastructure/reports/artifacts.py` (`_plan`, новый `assortment.json`, строки видов в `_interpretations`)
- Test: расширить `tests/test_assortment_pipeline.py`, `tests/test_pipeline_synthetic.py`

- [ ] **Step 1: Тест** — текст объяснения содержит имя вида, процент, хотя бы одну причину с `rule_id` (для вида с правилом рода) и слово «Альтернативы:»; `plan.json` содержит блок `assortment` у посадки; `assortment.json` существует и содержит `counts`, `shannon`, `decor_by_month` с ключами 1–12; в `interpretations.csv` есть строки с `rule_id` запрета/правила рода для посадок, где они применялись.

- [ ] **Step 2: Реализация** — в `_placement` после ограничений: «Вид: {name_ru} ({percent}%): {reasons через «; »}. Альтернативы: {code: percent}.»; причины `norm` печатаются с `rule_id` и цитатой, `reference` — с источником, `pilot` — «в N паспортах пилота». В `artifacts._plan` — сериализация `AssortmentInfo`; `assortment.json` — `AssortmentSummary`; `_interpretations` — по одной строке на причину `norm` с `rule_id`.

- [ ] **Step 3: Тесты, линтеры. Commit** — `feat(assortment): explanations, plan.json fields and assortment.json`

---

### Task 10: Существующая популяция из перечётной ведомости

**Files:**
- Create: `src/green/infrastructure/inventory.py`
- Modify: `src/green/application/ports.py` (`InventorySource`), `src/green/application/use_case.py` (`PlanRequest.inventory: Path | None`), `src/green/interfaces/cli/main.py` (`--inventory`), `src/green/interfaces/api/routers/runs.py` (необязательный файл `inventory`)
- Modify: `pyproject.toml` (`openpyxl`, `xlrd` — чтение xlsx/xls без pandas)
- Test: `tests/test_inventory.py`

- [ ] **Step 1: Тест** — из xlsx с колонками перечётки (`№№`, `Наименование`, `Кол-во в шт.`, `Заключение`) с деревьями «Клен ясенелистный» ×3 (одно «Удалить»), «Липа» ×2, «Самосев до 8 см.» ×1 получить `{"acer_negundo": 2, "tilia_cordata": 2}` — удаляемые не считаются, самосев не сопоставляется и уходит в `unmatched`.

- [ ] **Step 2: Реализация** — поиск строки заголовков по слову «Наименование», сопоставление русских названий с каталогом по первым двум словам без регистра (`Species.name_ru`), `xlrd` для `.xls`, `openpyxl` для `.xlsx`; возврат `InventoryCounts(matched, unmatched)`; в `use_case` — передать `matched` в `assign_species(existing=...)`, `unmatched` — в предупреждения.

- [ ] **Step 3: Прогон на Берзарина** — `uv run green run dataset/dxf/berzarina/ГП_исходный.dxf --profile strict --inventory "dataset/streets/Пилотный проект 20 улиц/16. улица Берзарина/Исходные данные/Перечетка_улица Берзарина.xls"`; в `assortment.json` появляется `existing` с породами; записать числа в `docs/notes/04-issues-and-fixes.md`.

- [ ] **Step 4: Тесты, линтеры. Commit** — `feat(inventory): count existing species from the tree survey for diversity quotas`

---

### Task 11: Документация и контрольные прогоны

**Files:**
- Modify: `docs/algorithm.md` (раздел «7a. Подбор ассортимента» между отбором и объяснениями; схема — узел «Подбор вида: фильтры, оценка, назначение с квотами»), `README.md` (артефакт `assortment.json`, `--inventory`), `CLAUDE.md` (карта: `application/assortment/`, `config/species.yaml` v2, `docs/species.md`), `docs/notes/04-issues-and-fixes.md` (что нашли на прогонах)

- [ ] **Step 1: Прогон Берзарина и Олимпийской деревни** (`strict`, режим `auto`): записать в заметку число видов, доли, Шеннон, `no_species`, время стадии `assort`, солвер; приложить пример объяснения одной посадки.

- [ ] **Step 2: Документация** по списку файлов.

- [ ] **Step 3: Полный прогон проверок** — `uv run ruff check src tests && uv run ruff format --check src tests && uv run ty check src && uv run lint-imports && uv run pytest -q`.

- [ ] **Step 4: Commit и PR** — `docs(assortment): algorithm section, species catalog guide and control runs`; `gh pr create --base main --head feat/assortment`.

---

## Что изменилось при исполнении (16.09.2026)

План писался до кода, и семь решений в нём оказались неверными. Здесь они перечислены, чтобы
план не расходился с тем, что работает; подробности - в `docs/algorithm.md`, раздел 7a.

1. **Прибавка за крону применяется не ко всей табл. 9.1.** Буквальное применение примечания
   ко всем строкам таблицы запрещает липу с кроной 12 м в двух метрах от борта: на
   контрольном прогоне 720 из 800 отказов дал один бортовой камень. Прибавка применяется к
   классам из нового параметра `crown_extra_classes` (по умолчанию здания и сооружения) -
   там, где крона физически мешает.
2. **Аллергенность - не фильтр, а штраф в оценке.** Запрета на аллергенные виды ни один акт
   не устанавливает; 743-ПП п. 3.6.18 говорит о засоряющих (пух, плоды). Пух остаётся
   жёстким фильтром с нормой, аллергенность снижает фактор `site` у жилья.
3. **Задача решается по структурам, а не по посадкам.** Переменная на каждую пару «посадка -
   вид» вместе с квотами дала 3,3 секунды на сорок посадок; переменная на пару «структура -
   вид» - 0,1 секунды и вдвое больше видов в плане. Однородность ряда обеспечена моделью, а
   не ограничением, поэтому `group_max_species` исчез, а вместо него появился
   `structure_patch_size`: крупный кластер делится на участки, и аллея меняет породу
   кварталами.
4. **Квоты мягкие, а не жёсткие, и их две.** Жёсткая квота несовместима с однородностью
   ряда (10% от тридцати посадок - три дерева, ряд из десяти требует десяти). Каждая доля
   проверяется в плане и в популяции с существующими деревьями, цены превышения разные.
5. **Заданные количества - верхняя граница.** Ряд не делится между двумя видами, поэтому
   25 лип на рядах по 10 дают 25 только при частичном заполнении участка, а остаток, если он
   не влез, называется в предупреждении.
6. **`structure_penalty` удалён.** С одним видом на структуру он ничего не менял, но замедлял
   решатель в 4-9 раз. Вместо него появился `assortment_solver` (`auto` / `greedy`).
7. **Перечётка отдаёт не только счётчики.** `InventoryCounts` несёт строки прочитанные,
   сопоставленные, не опознанные, к вырубке и без количества, и проверку баланса: отчёт,
   показывающий только то, что доехало, не отличает потерю от успеха.

## Self-review

- Покрытие спецификации: §3 → Task 1–2; §4 → Task 3; §5 → Task 5; §6 → Task 6; §7 → Task 4, 7, 8; §8 → Task 8–9; существующая популяция → Task 10; документация → Task 11. Режим `given` — Task 5 (фильтр) и Task 7 (счётчики). Режим `single` — Task 5 и 8.
- Точки подключения: `use_case.py` (Task 8), `repositories.py` через совпадение имён полей `ProfileModel`/`PlanParams` (Task 5), `artifacts.py` (Task 9), CLI/API (Task 10), сквозной тест Кирилла (Task 8, Step 3).
- Типы: `Reason`, `SpeciesVerdict` (Task 5) используются в `AssortmentInfo` (Task 8) и объяснениях (Task 9); `Score`/`percent` (Task 6) — в `Alternative.percent` и `AssortmentInfo.percent` (Task 8); `Structure` (Task 4) — в `Candidate.structure_id` (Task 7) и `SiteContext.structure_*` (Task 3/8).
- Проверка каждого элемента перечислений: фильтры §5 — по одному тесту на фильтр (Task 5), режимы `auto`/`given`/`single` — Task 7, 8.
