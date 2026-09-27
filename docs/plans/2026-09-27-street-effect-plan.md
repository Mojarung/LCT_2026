# Street Effect Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** баланс озеленения «было - стало», виды посадок и эффект для улицы в сервисе, индексе,
отчётах и сводке PDF.

**Architecture:** существующие насаждения читаются из объектов чертежа один раз
(`application/stock.py`) и едут в `Site` индекса; эффект считается чистой функцией от плана,
участка и насаждений (`application/effect.py`) и хранится в `Plan.effect`; место посадки -
`application/places.py` по зонированию или полигонам проезжей части. Исполнение - в этой сессии
(native), срок 29.09 23:59 МСК.

**Tech Stack:** Python 3.14, shapely 2, numpy, scipy; pytest; React + vitest; сборка PDF
`tools/docs/build.py`.

**Spec:** `docs/plans/2026-09-27-street-effect-design.md`

## Global Constraints

- Ветка `feat/docker-norms-docs`, коммиты без атрибуции агента, в main не пушить.
- Зелёные перед каждым коммитом: `uv run ruff check src tests tools`, `uv run ruff format --check src tests tools`, `uv run ty check src`, `uv run lint-imports`, `uv run pytest -q`.
- Домен без импорта application (import-linter).
- В текстах отчётов и документации нет длинных тире и эмодзи; десятичная запятая в текстах для людей.
- Существующие насаждения только в `Site.stock`; «было - стало» не смешивается с индексом.
- Посадка, прошедшая нормы, индекс не снижает (монотонность, тест обязателен).
- Тяжёлые прогоны по одному; убитый фоновый прогон не перезапускать без вопроса пользователю.

## Review Focus

1. Чертёж без существующих деревьев и без бортов: эффект и индекс не падают, пишут «нет данных».
2. Метки знаков деревьев вне границы работ: в «было» не входят, кроны у борта учитываются.
3. Полосы деревьев (MultiPoint `TREE_STRIP`): не считаются стволами.
4. Прогон с перечёткой: число «было» по деревьям из перечётки, вырубка по графе «Заключение».
5. План без посадок (Харьковский проезд): «стало» = «было», шум и ярусность без деления на ноль.

---

### Task 1: Existing stock

**Files:**
- Create: `src/green/application/stock.py`
- Modify: `src/green/application/quality/site.py` (поле `Site.stock`, `site_of(..., crown_m=...)`)
- Modify: `src/green/application/params.py` (`existing_crown_m: float = 8.5`), `src/green/infrastructure/config/schemas.py`, `tools/docs/annexes.py` (PARAMS)
- Modify: `src/green/application/use_case.py`, `src/green/application/editing.py` (передать `params.existing_crown_m`)
- Test: `tests/test_stock.py`

**Interfaces:**
- Produces: `Stock(trees_xy: NDArray (n,2), trees_radius: NDArray (n,), inside: NDArray[bool] (n,), marks: int, source: str, strips_xy: NDArray (m,2), shrubs_xy: NDArray (k,2), shrubs_inside: NDArray[bool])`, `Stock.trees -> int` (внутри границы), `Stock.shrubs -> int`, `stock_of(features, boundary, crown_m) -> Stock`, `EMPTY_STOCK`.
- Правила: вставка знака (`feature.symbol` и точка) - один ствол; прочие метки класса `existing_tree` (центр круга или центроид) склеиваются одиночной связью при 1,0 м, ствол - среднее; метки ближе 1 м к стволу-знаку входят в него; `TREE_STRIP` - в `strips_xy`, не стволы; берутся стволы внутри границы, буферизованной на радиус кроны (кроны у борта), `inside` - внутри самой границы; радиус кроны - `crown_m / 2`.

- [ ] Step 1: тесты: два знака и 30 штрихов вокруг третьего дерева -> 3 ствола, `source="mixed"`; штрихи на 1,5 м -> два ствола; MultiPoint полосы не ствол; ствол вне границы не в `trees`, но в `trees_xy`, если крона достаёт; нет границы -> `EMPTY_STOCK`.
- [ ] Step 2: `uv run pytest tests/test_stock.py -q` - FAIL.
- [ ] Step 3: реализация `stock.py`, `Site.stock`, параметр.
- [ ] Step 4: тесты зелёные, весь набор зелёный.
- [ ] Step 5: коммит `feat(stock): existing trees and shrubs of the drawing for the index and the balance`.

### Task 2: Index counts existing crowns

**Files:**
- Modify: `src/green/application/quality/terms.py` (`canopy`, `dust`, `tiers`, `_under_crowns`)
- Test: `tests/test_quality_existing.py`

**Interfaces:**
- Consumes: `Site.stock`.
- `canopy`: объединение кругов новых и существующих крон в границе; уникальная площадь дерева - за вычетом всех остальных, включая существующие; `measure` добавляет `existing_m2`.
- `dust`: существующие кроны идут в `measure_crowns` с весом `dust_crown_factor * 0.5` (газоустойчивость неизвестна - средняя); `deltas` только у новых посадок; `measure` добавляет `existing_covered_m`.
- `tiers`: `covered` += существующие деревья, под кроной которых есть новый кустарник; цель прежняя; куст, единственный под существующим деревом, получает вклад.

- [ ] Step 1: тесты: новая крона внутри существующей не меняет `canopy.score`; куст у борта под существующей кроной увеличивает `dust`; существующее дерево с новым кустом под кроной увеличивает `tiers.measure["covered"]`; добавление посадки не снижает индекс на плане с существующими деревьями; без `stock` значения совпадают с прежними (регрессия на `tests/test_quality*.py`).
- [ ] Step 2: FAIL.
- [ ] Step 3: реализация.
- [ ] Step 4: зелёные.
- [ ] Step 5: коммит `feat(quality): shade, dust protection and tiers count existing crowns`.

### Task 3: Understory under existing trees

**Files:**
- Modify: `src/green/application/understory.py`, `src/green/application/params.py` (`understory_existing: bool = True`, `understory_existing_gap_m: float = 3.0`), `schemas.py`, `annexes.py`
- Test: `tests/test_understory_existing.py`

**Interfaces:**
- Consumes: `stock_of` (из `features` и границы).
- `_Planter.under_at(x, y, radius, key, min_ring)`: общий код для нового и существующего дерева; у существующего кольца от `understory_existing_gap_m` (743-ПП п. 9.8: траншеи не ближе 3 м от ствола толще 15 см, по аналогии), `structure = "under-existing-<n>"`, пометка причины «под кроной существующего дерева».
- Порядок: сначала новые деревья (аллея первой), затем существующие внутри границы; общий потолок кустарника В.1.

- [ ] Step 1: тесты: под существующим деревом группа ставится, все кусты не ближе 3 м к стволу; при `understory_existing=False` не ставится; дерево с существующим кустом под кроной не трогается.
- [ ] Step 2-4: FAIL, реализация, зелёные.
- [ ] Step 5: коммит `feat(understory): shrub groups under existing trees, 3 m from the trunk`.

### Task 4: Street effect

**Files:**
- Create: `src/green/domain/effect.py` (`EffectMeasure`, `PlantingKind`, `NoiseBand`, `StreetEffect`)
- Create: `src/green/application/effect.py` (`street_effect(plan, site, params, inventory) -> StreetEffect`)
- Modify: `src/green/domain/planting.py` (`Plan.effect: StreetEffect | None = None`)
- Test: `tests/test_effect.py`

**Interfaces:**
- `EffectMeasure(key, title, unit, before: float | None, after: float | None, basis: str, kind: str, note: str)`; `kind` - `"norm"` (норма с числом) или `"requirement"` (требование без числа) или `"count"`.
- `PlantingKind(key, title, planting_type, count, length_m: float | None, area_m2: float | None, basis)`.
- `NoiseBand(width_from_m, width_to_m, dba_mgsn: str, curb_before_m, curb_after_m)`.
- `StreetEffect(measures, kinds, noise, notes, stock_source)`.
- Показатели: `trees`, `shrubs`, `canopy_m2`, `canopy_share`, `curb_green_m`, `curb_green_share`, `tiers_trees`, `species_new`, `trees_per_km`, `shrubs_per_km`, `lawn_m2`, `noise_curb_m`. Пылезащита «было - стало» без весов газоустойчивости: доля длины бортов под кронами и полосой `dust_strip_m` у кустарника.
- Шум: борт через 2 м, нормали в обе стороны до 35 м; зелень - объединение крон и кустарника (существующих и новых), закрытие разрывов до 4 м (буфер +2/-2); ширина полосы - отрезок нормали в зелени, начинающийся не дальше 2 м от борта, берётся большая из сторон; полосы по табл. В.5 МГСН: 10-15 (4-5 дБА), 16-20 (5-8), 21-25 (8-10), 26 и больше (10-12); рядом СП 276 п. 7.8: 0,08 дБА/м.
- Виды посадок - по первой пометке приёма (`MODE_LABELS`) и газонам (`LawnKind`); длина изгороди = число x `curb_hedge_spacing_m`, ряда = число x `shrub_row_spacing_m`.
- Перечётка: «было» деревьев = сумма `matched` + `unmatched`, в заметке - `rows_removed` как вырубка по решению проектировщика.

- [ ] Step 1: тесты на синтетике: пустой план -> «стало» = «было»; крона поверх существующей не меняет `canopy_m2`; куст у борта увеличивает `curb_green_m`; полоса 12 м зелени вдоль борта 50 м -> `noise` 10-15 м около 50 м «стало», 0 «было»; виды: изгородь из 10 кустов -> 10 м; перечётка задаёт «было» деревьев.
- [ ] Step 2-4: FAIL, реализация, зелёные.
- [ ] Step 5: коммит `feat(effect): street balance and before-after effect of the plan`.

### Task 5: Effect in the run and its artifacts

**Files:**
- Modify: `src/green/application/use_case.py` (после газонов: `plan = replace(plan, effect=street_effect(...))`), `src/green/application/editing.py` (пересчёт после правки)
- Modify: `src/green/infrastructure/reports/artifacts.py` (`quality.json` -> блок `effect`)
- Modify: `src/green/infrastructure/reports/interpretation_report.py` (раздел «Баланс озеленения и эффект» и «Посадки по видам» в HTML и MD)
- Test: `tests/test_effect_artifacts.py`, существующие тесты отчётов

- [ ] Step 1: тесты: прогон встроенного фрагмента (как в тестах сценария) пишет `quality.json["effect"]` с `measures` и `kinds`; `report.md` содержит «Баланс озеленения»; после правки эффект пересчитан.
- [ ] Step 2-4: FAIL, реализация, зелёные.
- [ ] Step 5: коммит `feat(reports): balance and before-after effect in quality.json and the interpretation report`.

### Task 6: Numbers for the PDF and the new summary

**Files:**
- Create: `tools/effect_from_runs.py` (контекст прогона -> `effect.json` рядом с артефактами, тот же `street_effect`)
- Modify: `tools/docs/annexes.py` (столбцы «было - стало» в приложении B, факты сводки: баланс по пилоту, функции)
- Modify: `docs/documentation/00-summary.md` (6 блоков спецификации), `03-algorithm.md` (разделы: существующие насаждения, эффект, виды посадок, шум, изменения индекса), `08-limitations.md`
- Create: `docs/requirements/approval-checklist.md` (чек-лист согласующего с источниками)

- [ ] Step 1: `uv run python tools/effect_from_runs.py --runs out/docker-batch` по одной улице за раз, проверить числа Багрицкого с прототипом (доля бортов под зеленью было около 14%).
- [ ] Step 2: приложения и сводка, `uv run python tools/docs/annexes.py`, `uv run python tools/docs/build.py`; просмотр страниц сводки (`node tools/docs/preview.mjs`).
- [ ] Step 3: коммит `docs(documentation): summary with the balance, planting kinds and before-after effect`.

### Task 7: Place of each planting

**Files:**
- Modify: `src/green/domain/objects.py` (`TERRITORY_STREET`, `TERRITORY_YARD`, `TERRITORY_SQUARE`, `TERRITORY_PARK`)
- Modify: `config/geo_layers.yaml`, `src/green/infrastructure/gis/layers.py` (`_Rule.any_value`: регулярное выражение по любому значению атрибутов)
- Create: `src/green/application/places.py` (`Place`, `PLACE_LABELS`, `PlaceMap`, `place_map(features)`, `category_of(place, default)`)
- Modify: `src/green/domain/planting.py` (`Placement.place: str = ""`), `use_case.py` (`with_places` после размещения и перед проверкой), `placement.py` (аллея не в месте «двор»), `assortment/context.py` + `filters.py` + `scoring.py` (категория по месту), `validation.py` (видовые нормы по категории места), `quality/terms.py` (`category` по месту), отчёты (столбец «место»), `effect.py` (место в видах посадок)
- Test: `tests/test_places.py`, `tests/test_gis_zoning.py`

**Interfaces:**
- `Place`: `roadside`, `yard`, `street`, `square`, `park`, `unknown`; `PlaceMap.source`: `zoning` | `road` | `none`; `PlaceMap.of(xy) -> list[Place]`.
- Двор по полигонам проезжей части: отрезок до ближайшей проезжей части пересекает здание; у проезжей части - ближе 10 м (`place_roadside_m = 10.0`).
- `category_of`: roadside, street -> `streets`; yard -> `yards`; square -> `squares`; park -> `parks`; unknown -> профиль.

- [ ] Step 1: тесты: зонирование с атрибутом «Жилая застройка, дворовая территория» -> yard; полигон проезжей части и здание между -> yard; без данных -> unknown и категория профиля; аллея не ставится в зоне двора; вид с «-» для дворов не назначается во дворе и проверка плана это ловит.
- [ ] Step 2-4: FAIL, реализация, зелёные.
- [ ] Step 5: коммит `feat(places): place of each planting from zoning or carriageway polygons`.

### Task 8: Before-after card in the web UI

**Files:**
- Modify: `frontend/src/api/artifacts.ts` (тип блока `effect`), `frontend/src/components/run/*` (карточка «Было - стало» рядом с индексом)
- Test: vitest рядом с компонентом

- [ ] Step 1-4: тест рендера карточки из фикстуры, реализация, `npm test`, `npm run build`, снимок playwright.
- [ ] Step 5: коммит `feat(web): before-after card on the run page`.

### Task 9: Rerun, image, final numbers

- [ ] Пересобрать образ Docker, перепрогнать улицы каталога по одной (`tools/street_runs.py`, пиковая память через `tools/peak_memory.py`), при нехватке памяти - вопрос пользователю.
- [ ] `annexes.py`, `build.py`, обновить оценочные файлы `docs/assessment/`, `CLAUDE.md` (карта, тесты).
- [ ] Коммит и push.
