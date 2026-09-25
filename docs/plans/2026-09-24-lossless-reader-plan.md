# Чтение DXF «один в один»: план реализации

> **Для исполнителя:** задачи выполняются по порядку, каждая через TDD: тест, падение, код,
> тест, коммит. Шаги отмечаются чекбоксами.

**Цель:** каждая улица каталога читается без тихих потерь и понимается правильно: одно дерево -
один объект, препятствия со своим классом, области REGION с геометрией, внешние ссылки комплекта
разрешены; доказательство - сборка улицы обратно и перепись растительности на всех 19 улицах.

**Архитектура:** ридер тиммейта (полная геометрия, учёт посещённого) остаётся основой. Над ним -
слой условных знаков (`SymbolInstance` + словарь `config/symbols.yaml`), классификация «знак >
слой», новые классы препятствий и существующих насаждений. Проверка вынесена в модуль сверки
(`fidelity`: всё, что CAD нарисовал бы, против разобранной сцены) и инструмент прогона по улицам.

**Стек:** Python 3.14, ezdxf 1.4.4 (drawing.recorder, acis), shapely 2, numpy, pytest;
matplotlib - только в dev-группе, для картинок отчёта.

**Спецификация:** `docs/plans/2026-09-24-lossless-reader-design.md`.

## Исходная картина (24.09.2026, ветка тиммейта, 19 улиц каталога)

- 12 улиц падают на загрузке: REGION без данных ACIS («N исходных сущностей невозможно
  сохранить»), на Старом Гае 12 856, на Академика Понтрягина 16 679; слои «Красные линии»,
  «Леса и газоны», «Полоса деревьев», «Лестницы набережных», сети. Причина - конвертация
  DWG->DXF в LibreDWG: у части файлов ACIS сохранён (разбирается ezdxf, проверено на 245
  областях), у части потерян.
- 2 улицы (Песчаный, Макеева) падают на аудите: вставки без определения блока.
- 5 улиц читаются, но у каждой 12 пробелов геометрии и тысячи неизвестных объектов, поэтому
  `require_complete_geometry` и `require_known_objects` останавливают прогон.
- Кустанайская: склейка комплекта не находит внешние ссылки файла границ
  (`00.1_10004141_Топография` против `00-1-10004141-topografiya.dxf`).

## Global Constraints

- Ядро `green.domain` + `green.application` без ezdxf, pydantic, yaml (контракт import-linter).
- Строгость тиммейта не ослабляется: неполные данные останавливают расчёт; меняется только то,
  что ложные остановки становятся полными данными или явно объяснёнными исключениями.
- Тихих потерь 0: каждый посещённый примитив имеет исход (объект, подпись, штрих знака, пропуск
  с причиной).
- Порог сборки: не больше 0,5% непокрытых чернил в окне 100 x 100 м (не аннотации).
- Датасет и ТЗ в git не кладутся; отчёты прогонов - в `out/reader-check/` (игнорируется).
- Коммиты - conventional, без подписи агента.

## Review Focus

- Знак внутри знака (обёртка MicroStation вокруг `DEREVO`): экземпляр один, внутренний.
- REGION внутри вставки с поворотом и масштабом: полигон в мировых координатах, не в блочных.
- Внешняя ссылка на основу комплекта со сдвигом вставки: отказ, а не молчаливая склейка.
- Один и тот же слой с разным смыслом на разных улицах («Береговая линия» - берег или желоб):
  класс не должен разрешать посадку ни в одном из смыслов.
- Точки «Полосы деревьев» реже 1,5 м - отдельные деревья, а не полоса.

---

### Задача 1. REGION: геометрия из ACIS

**Файлы:**
- Создать: `src/green/infrastructure/cad/acis_region.py`
- Изменить: `src/green/infrastructure/cad/reader.py` (REGION больше не в `_SKIPPED`; REGION внутри
  вставок читается с матрицей вставки)
- Тест: `tests/test_acis_region.py`

**Интерфейсы:**
- Даёт: `region_polygon(entity: Body, matrix: Matrix44 | None, flatten: float) ->
  tuple[BaseGeometry, float]` (полигон в единицах чертежа, граница ошибки) и исключение
  `RegionGeometryError(reason: str)` с причинами `missing-acis-data`, `unsupported-curve`,
  `non-planar`, `no-faces`.

- [ ] Тест: квадрат 10 x 10 из `acis.body_from_mesh` в REGION на R2000 -> полигон площадью 100.
- [ ] Тест: тот же REGION в блоке, вставка в (100, 50) с поворотом 90 градусов -> полигон с
  центром в (100 - 5, 50 + 5) и площадью 100.
- [ ] Тест: REGION без ACIS -> пробел `missing-acis-data` в `read_diagnostics.geometry_gaps`.
- [ ] Тест: область с дугой (ellipse-curve) -> полигон, ошибка аппроксимации не больше `flatten`.
- [ ] Реализация: `acis.load_dxf(entity)` -> тела -> грани -> петли -> коэджи; прямые рёбра по
  вершинам, ellipse-curve - разбор записи (центр, нормаль, большая ось, отношение, диапазон
  параметра) и ломаная с шагом по допуску; внешняя петля - наибольшая по площади, остальные -
  дырки; грани объединяются; матрица вставки применяется к вершинам.
- [ ] В ридере REGION идёт в `_geometry`; при `virtual_entities()` ezdxf пропускает REGION
  (не трансформируется) - `_insert` сам читает REGION блока с `insert.matrix44()`.
- [ ] Прогон тестов ридера тиммейта целиком, коммит `feat(cad): REGION geometry from ACIS`.

### Задача 2. Внешние ссылки комплекта

**Файлы:**
- Изменить: `src/green/application/semantic_names.py` (`slug_key`, таблица транслитерации),
  `tools/prepare_streets.py` (берёт `slug_key` из ядра),
  `src/green/infrastructure/cad/xref_package.py` (`_match` + ссылка на основу)
- Тест: `tests/test_xref_package.py`

**Интерфейсы:**
- Даёт: `slug_key(name: str) -> str` («00.1_10004141_Топография» ->
  «00-1-10004141-topografiya»); действие привязки `provided_as_input`.

- [ ] Тест: `slug_key` совпадает с прежним `slugify` каталога на именах всех 19 улиц.
- [ ] Тест: комплект «основа + сети + границы», файл границ ссылается на основу и сети их
  исходными CAD-именами (`00.1_X_Топография.dwg`), файлы комплекта названы как в каталоге -
  склейка проходит; основа не задвоена; сети внедрены; действия привязок записаны.
- [ ] Тест: та же ссылка на основу, но вставка со сдвигом (10, 0) -> `InputError`.
- [ ] Реализация: `_match` после точного и базового имени сравнивает `slug_key` основы имени
  файла без расширения, неоднозначность - ошибка; ссылка на индекс 0 (основу) не делает основу
  «ссылаемой», а помечается `provided`; `_resolve` проверяет, что все вставки блока ссылки -
  (0, 0, 0), масштаб 1, поворот 0, снимает флаги XREF с пустого блока и пишет привязку
  `provided_as_input`.
- [ ] Коммит `fix(cad): resolve kit xrefs by catalog names, base provided as input`.

### Задача 3. Экземпляры условных знаков и учёт исходов в ридере

**Файлы:**
- Изменить: `src/green/domain/objects.py`, `src/green/infrastructure/cad/reader.py`
- Тест: `tests/test_reader_symbols.py`

**Интерфейсы:**
- Даёт (домен):
  ```python
  @dataclass(frozen=True, slots=True)
  class SymbolInstance:
      ref: SourceRef
      block: str              # полное имя блока
      layer: str              # слой вставки после наследования
      x: float                # точка вставки, метры
      y: float
      rotation_deg: float = 0.0
      scale: float = 1.0
      strokes: int = 0        # сколько примитивов знака прочитано
  ```
  `Scene.symbols: tuple[SymbolInstance, ...] = ()`, `Feature.symbol: str | None = None`,
  `TextLabel.symbol: str | None = None` (строка `str(ref)` экземпляра-владельца),
  `ReadDiagnostics.outcomes: Mapping[str, int]`.
- Контейнер, а не знак: локальное имя блока начинается с `msdElementType`, `DIMTXT` или `*`,
  блок пустой, либо в нём больше 64 примитивов, либо его габарит с масштабом вставки больше 12 м.
- Исходы: `feature`, `label`, `label:empty`, `insert:symbol`, `insert:container`,
  `insert:multi`, `insert:xref-unresolved`, `insert:no-block`, `insert:too-deep`,
  `insert:xclip`, `insert:not-explodable`, `skipped:<ТИП>:<причина>`.

- [ ] Тест: три вставки `DEREVO_1..3` (эллипс, круг, линия) -> три экземпляра, девять
  штрихов со ссылкой на свой экземпляр, точки вставки в метрах.
- [ ] Тест: `DEREVO` внутри обёртки `msdElementType_5` -> один экземпляр `DEREVO`, обёртка -
  контейнер.
- [ ] Тест: `DIMTXT` с текстом и выноской -> контейнер, подпись без владельца.
- [ ] Тест: сумма исходов равна сумме посещённых на чертеже со всеми типами (текст, пустой текст,
  вставка без блока, MINSERT, REGION без ACIS, подпись с выравниванием без точки).
- [ ] Реализация в `_Walker`: параметр `owner`, счётчик `outcomes`, кэш габаритов блоков,
  экземпляр создаётся до обхода детей; `_to_metres` переводит и экземпляры.
- [ ] Коммит `feat(cad): symbol instances and a per-primitive outcome ledger`.

### Задача 4. Перепись знаков по 19 улицам и словарь

**Файлы:**
- Создать: `src/green/infrastructure/cad/census.py`, `tools/reader_kits.py` (комплект улицы из
  каталога, склейка с кэшем в `out/reader-check/cache/`), `tools/symbol_census.py`,
  `config/symbols.yaml`
- Тест: `tests/test_census.py`
- Изменить: `pyproject.toml` (`uv add --dev matplotlib`)

**Интерфейсы:**
- Даёт: `insert_census(doc: Drawing) -> list[InsertRecord]` с полями `block`, `base`, `layer`,
  `x`, `y`, `depth` - независимый от ридера обход вставок-знаков (тот же критерий контейнера).
- `base_name(block: str) -> str`: локальное имя без префикса XREF и числового суффикса
  (`output[1]_tp$0$DEREVO_935` -> `DEREVO`) - в `semantic_names.py`.

- [ ] Тест: `base_name` на именах из тестов тиммейта и на `DEREVO_935`, `KUST1_162`, `SM_1_3`
  (-> `SM_1`: суффикс - только последняя группа цифр после знака `_`, если перед ним не
  одиночная буква или цифра имени; правило уточняется по переписи).
- [x] Тест: перепись синтетического чертежа совпадает с экземплярами ридера по числу и точкам
  (обёртка MicroStation с поворотом, вставка массивом 2 x 3; `census.insert_census` обходит
  вставки матрицами, ридер - virtual_entities; пороги контейнера общие, из ридера).
- [ ] Инструмент: все улицы каталога -> `out/reader-check/census/symbols.json` (базовое имя,
  число, слои, улицы, пример рисунка) и листы знаков PNG по 48 на лист.
- [ ] Словарь `config/symbols.yaml`: каждое базовое имя -> класс, роль (`point`, `marker`,
  `geometry`, `annotation`), примечание, источник (УЗ 1:500, `Шаблоны значков.dxf`, рисунок).
  Сомнительные - отдельным листом пользователю.
- [ ] Коммит `feat(config): symbol dictionary from the census of all 19 streets`.

### Задача 5. Классификация «знак > слой»

**Файлы:**
- Создать: `src/green/application/symbols.py` (`SymbolCatalog`, `SymbolEntry`, роли)
- Изменить: `src/green/infrastructure/config/schemas.py`, `.../repositories.py`
  (`YamlSymbolCatalogSource`), `src/green/application/classification.py`,
  `src/green/bootstrap/container.py`, `src/green/application/use_case.py`, `audit.py` и прочие
  вызовы `classify_scene`
- Тест: `tests/test_symbol_classification.py`

**Интерфейсы:**
- `classify_scene(scene, layer_map, params=None, symbols: SymbolCatalog | None = None)`:
  1. экземпляр -> запись словаря по `base_name` или неизвестен;
  2. штрих известного знака: роли `point`, `marker`, `annotation` -> `IGNORE` с доказательством
     `symbol_stroke`; роль `geometry` -> класс словаря;
  3. для `point` и `marker` добавляется объект-якорь: `Point(x, y)`, класс словаря, `block`,
     `source_entity_type="INSERT"`, `symbol=str(ref)`;
  4. явные уточнения пользователя (`feature/block/layer_classes`) сильнее словаря;
  5. отчёт: число экземпляров по классам, неизвестные базовые имена с числом.

- [ ] Тест: три `DEREVO` -> три `existing_tree` точки в точках вставки, штрихи `ignore`.
- [ ] Тест: `KUST1` -> `existing_shrub`.
- [ ] Тест: знак `RESHT1` на слое, который правила слоёв игнорируют -> класс словаря.
- [ ] Тест: неизвестный знак -> штрихи по слою, имя в `unknown_symbols` отчёта.
- [ ] Тест: `block_classes` пользователя переопределяет якорь.
- [ ] Коммит `feat(classification): symbols decide before layers`.

### Задача 6. Классы препятствий и насаждений, причины игнора

**Файлы:**
- Изменить: `src/green/domain/objects.py` (`OBSTACLE = "obstacle"`,
  `EXISTING_WOODLAND = "existing_woodland"`), `src/green/application/explain.py` (подписи),
  `config/rules.yaml` (`R-OBST-TREE-001` 1,0 м и `R-OBST-SHRUB-001` 0,5 м до края, акт
  `PROJECT`), `config/layer_map.yaml` (причины, новые правила слоёв по переписи),
  `src/green/infrastructure/config/schemas.py` (`reason` обязателен для `ignore`)
- Тест: `tests/test_layer_map.py`, `tests/test_rules_cover_classes.py`

- [x] Тест: правило `ignore` без `reason` не загружается; причина доходит до отчёта.
- [x] Тест: у каждого класса, по которому сажать нельзя, есть правило расстояния для дерева
  и кустарника (кроме `ignore`, `unknown`, `lawn`, `work_boundary`, `existing_woodland` - он
  через покрытия; у кустарника ещё водопровод, канализация, водосток, дренаж, газ - прочерк в
  табл. 9.1). Тест нашёл 9 пар без правила: объект без правила размещению не виден вовсе.
- [x] Тест: точка внутри замкнутого `obstacle` отклоняется правилом `R-OBST-TREE-001`
  (`ObjectClass.occupies_interior`, индекс строит площадь по замкнутому контуру).
- [x] Слои по переписи: «Крыльца», «Фонтаны», «Памятники», «Береговая линия» -> `obstacle`;
  «Вентиляторы» -> `structure`; «Красные линии» -> `ignore` с причиной «граница планировки».
- [x] Коммит `feat(norms): obstacle and woodland classes, reasons for ignored layers`.

Отличие от плана (25.09.2026): до препятствия дерево 1,1 м, а не 1,0 м. Это половина стороны
ямы 2,2 x 2,2 м из параметров проекта: при 1,0 м яма заходила бы на объект. Тем же посадочным
местом закрыты ограда, существующий куст, ствол, опора и люк (правила `PROJECT`).

### Задача 7. Полосы деревьев

**Файлы:**
- Создать: `src/green/application/tree_strips.py`
- Изменить: `src/green/application/classification.py` (вызов после классификации)
- Тест: `tests/test_tree_strips.py`

**Интерфейсы:** `chain_tree_strips(features, *, spacing_m=1.5, min_points=3) ->
tuple[Feature, ...]` - точки `existing_tree` без владельца-знака, ближе `spacing_m` друг к другу,
цепочкой от `min_points` -> один объект `MultiPoint` с доказательством `tree_strip`.

- [x] Тест: 20 кружков через 0,8 м -> одна полоса, `MultiPoint` из 20 точек; кружки остаются
  в сцене с классом `ignore` и доказательством `tree_strip_member:<ссылка полосы>` (учёт цел).
- [x] Тест: пять деревьев через 5 м -> пять отдельных деревьев.
- [x] Тест: якоря знаков `DEREVO` через 1 м не склеиваются (это настоящие деревья).
- [x] Тест: затравка грунта карты покрытий - в каждом кружке полосы, а не в её центре (центр
  Г-образной полосы лежит вне неё).
- [x] Коммит `feat(classification): tree strip symbols become strips, not trunks`.

### Задача 8. Покрытия: знаки газона и насаждений

**Файлы:**
- Изменить: `src/green/application/surfaces.py` (`_seeds`: точки `lawn` и `existing_woodland` -
  признак грунта; `SurfaceMap.woodland_area`; `fits_soil` исключает насаждения),
  `src/green/application/surface_faces.py` (`woodland_xy` -> `FaceMaterials.woodland`)
- Тест: `tests/test_surface_woodland.py`

- [x] Тест: замкнутая грань со знаком `GAZON` без подписи - грунт (раньше карта без подписей
  не строилась вовсе, и в такой грани посадок не было).
- [x] Тест: грань со знаком `LISTVL` - грунт, но `fits_soil` ложно внутри неё и при нулевом
  радиусе; `SurfaceMap.woodland_area` - грани со знаком массива, в том числе неразрешённые.
- [x] Коммит `feat(surfaces): lawn and woodland symbols as face evidence`.

Ограничение: исключение массива работает в режиме замкнутых граней (по умолчанию). В режиме
заливки по расстоянию знак массива не участвует: границы массива без контура не определить.

### Задача 9. Сборка улицы обратно (fidelity)

**Файлы:**
- Создать: `src/green/infrastructure/cad/fidelity.py`
- Тест: `tests/test_fidelity.py`

**Интерфейсы:**
```python
@dataclass(frozen=True, slots=True)
class InkMiss:
    handle: str
    entity_type: str
    layer: str
    missed_m: float        # непокрытая длина (линии) или периметр непокрытой площади
    x: float
    y: float

@dataclass(frozen=True, slots=True)
class WindowScore:
    x0: float
    y0: float
    ink_m: float
    missed_m: float

@dataclass(frozen=True, slots=True)
class FidelityReport:
    ink_m: float
    missed_m: float
    annotation_missed_m: float
    windows: tuple[WindowScore, ...]
    misses: tuple[InkMiss, ...]

def fidelity(doc: Drawing, scene: Scene, *, tolerance_m: float = 0.15,
             window_m: float = 100.0) -> FidelityReport: ...
```
- Исходник рисуется `Frontend(RenderContext(doc), Recorder(), Configuration(text_policy=IGNORE,
  hatch_policy=SHOW_SOLID, ...))`; каждая запись -> линии или полигоны в метрах с handle;
  покрытие - по буферу разобранной сцены (до классификации) в `tolerance_m`: сначала векторно
  «запись целиком внутри буфера одного объекта», остаток - точной разностью; аннотации
  (`DIMENSION`, `LEADER`, `MULTILEADER`, `ATTDEF`) считаются отдельно.

- [x] Тест: полная сцена (отрезок, круг, дуга, полилиния, штриховка, знак с поворотом) ->
  `missed_m == 0`.
- [x] Тест: сцена без одного отрезка 12 м -> `missed_m` = 12 с его handle.
- [x] Тест: штриховка покрыта полигоном; широкая полилиния покрыта осью с шириной и
  посчитана в `wide_polylines`; размер - в отдельном счёте оформления.
- [x] Коммит `feat(cad): street reconstruction check against a CAD render`.

Как сделано: текст не рисуется, штриховка - контуром, типы линий - сплошной, точки - точкой;
линии режутся на куски не длиннее допуска, середина куска ищется в STRtree сцены
(`query_nearest` с пределом). У залитых фигур допуск шире на половину толщины 2S/P (не больше
1 м): ридер хранит ось полилинии с шириной. Кустанайская (25.09.2026): 137,7 км чернил,
пропущено 0,4 м (0,000%), худшее окно 0,006%; пропуск - полилиния «ДВ_ГП_П_Граница работ», тот
же пробел, что называет учёт исходов. Чтение 35 с, сверка 87 с.

### Задача 10. Перепись растительности

**Файлы:**
- Создать: `src/green/application/vegetation.py`
- Тест: `tests/test_vegetation_census.py`

**Интерфейсы:** `vegetation_census(records: Sequence[CensusRecord], scene: Scene, catalog:
SymbolCatalog) -> VegetationCensus` - по каждому классу растительности (`existing_tree`,
`existing_shrub`, `existing_woodland`, `lawn`-знаки, полосы): число в исходнике, число в сцене,
расхождения с координатами. `CensusRecord(base, layer, x, y)` - простая запись ядра, которую
заполняет инфраструктурная перепись.

- [x] Тест: сцена из задачи 5 -> совпадение по каждому классу.
- [x] Тест: сцена с потерянным якорем -> расхождение с точкой.
- [x] Тест: явное уточнение меняет класс якоря, но это не потеря (сверка по коду знака).
- [x] Коммит `feat(application): vegetation census against the source`.

Источник - `census.insert_census` (задача 4), стволы и полосы без знака считаются
отдельно (`loose_trunks`, `strips`, `strip_points`): их источник - сами кружки.

### Задача 11. Прогон по улицам и отчёт

**Файлы:**
- Создать: `tools/reader_check.py`
- Изменить: `docs/notes/32-lossless-reading.md` (новая заметка), `CLAUDE.md` (карта)

- [ ] Инструмент: `uv run python tools/reader_check.py --streets all` -> на улицу:
  склейка (как в сервисе), чтение, `require_complete_geometry`, классификация, учёт исходов,
  сборка, перепись растительности, неизвестные знаки; `report.md`, картинки худших окон
  (серым исходник, красным непокрытое), JSON; сводка `out/reader-check/summary.md`.
- [ ] Прогон всех 19 улиц; каждое нарушение критерия - исправление в задачах 1-10 или явное
  объяснение в заметке; повтор до выполнения критерия на всех улицах.
- [ ] Коммит `test(cad): reader check across all 19 streets`.

### Задача 12. Конвертация без потерь (ODA File Converter)

Зависит от установки ODA File Converter пользователем или с его разрешения.

**Файлы:**
- Изменить: `tools/prepare_streets.py` (`--converter oda|libredwg`, отчёт конвертации: REGION с
  ACIS и без, вставки без блока), `docs/notes/26-street-catalog.md`

- [ ] Перепись REGION по всем файлам после LibreDWG (есть: `C:/Temp/claude/region_census.jsonl`).
- [ ] Переконвертация файлов, где ACIS потерян, через ODA; повтор переписи - потерь 0.
- [ ] Повтор задачи 11 на новых файлах.
- [ ] Коммит `fix(tools): convert the street catalogue without losing REGION data`.

### Задача 13. Сквозной прогон сервиса

- [ ] `green run` по каждой из 19 улиц в профиле `strict`: чтение и классификация проходят,
  план строится; число посадок и отказов - в заметку 32.
- [ ] Полный набор тестов, ruff, ty, import-linter.
- [ ] Коммит и пуш ветки `feat/lossless-reader`.

## Самопроверка плана

- Требования спецификации 1-7 покрыты задачами 3 и 5 (знаки), 4 (словарь), 5-6 (порядок,
  причины), 2 (внешние ссылки), 3 (учёт), 9 (сборка), 10 (растительность), 11 (19 улиц).
- Сверх спецификации по фактам переписи: задача 1 (REGION) и задача 12 (конвертер) - без них
  12 улиц из 19 не читаются вовсе.
