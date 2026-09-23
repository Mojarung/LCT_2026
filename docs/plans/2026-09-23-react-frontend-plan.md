# Фронтенд на React: план реализации

> **Для исполнителя:** выполнять по задачам сверху вниз, шаги отмечать чекбоксами. Спека:
> `docs/plans/2026-09-23-react-frontend-design.md` - читать вместе с планом.

**Цель:** заменить страницы Jinja2 и `plan.js` одностраничным приложением на React с тем же
набором возможностей, закрыть найденные на клиенте дефекты и сдать фронт, проверенный тестами,
скриншотами, a11y-сканом и жюри дизайна.

**Архитектура:** SPA в `frontend/` (Vite) собирается в `frontend/dist`; FastAPI раздаёт бандл и
JSON API с одного адреса. Карта - движок на TypeScript без React (перенос `plan.js`), React
рисует страницы и панели. Docker собирает бандл в стадии на node, в рабочем образе node нет.

**Стек:** React 19, TypeScript (strict), Vite, React Router 7, TanStack Query 5, Zustand 5,
Vitest + Testing Library, Playwright, ESLint 9 (typescript-eslint, react-hooks, jsx-a11y),
Prettier, openapi-typescript. Бэкенд: FastAPI, pytest.

## Общие ограничения

- Python-гейты зелёные: `uv run ruff check src tests`, `uv run ruff format --check src tests`,
  `uv run ty check src`, `uv run lint-imports`, `uv run pytest`.
- Фронт-гейты зелёные: `npm run typecheck`, `npm run lint`, `npm run format:check`, `npm test`.
- Ни одного запроса страницы за пределы своего адреса: шрифты, иконки, swagger-ui - в бандле.
- Тексты интерфейса по-русски; без длинного тире в тексте интерфейса, без эмодзи-иконок,
  без КАПС-заголовков больше одного уровня (стоп-лист `taste` и вердикт жюри, итерация 3).
- Токены цвета, шрифты и визуальный язык - из нынешнего `app.css`; IBM Plex - локальные файлы.
- Существующие эндпоинты API не меняют форму ответа; только добавления. Веб-маршруты Jinja2
  удаляются в задаче 13, не раньше: до неё старый интерфейс продолжает работать.
- Ветка `feat/react-frontend`, conventional commits, без подписи агента, пуш только этой ветки.
- Порт 8000 занят контейнером `lct_2026-api-1`: для проверок бэкенд поднимается на своём порту,
  готовность проверяется по содержимому `/api/v1/meta`, а не по коду 200.

---

### Задача 1: прогон по улице через JSON API

**Файлы:**
- Изменить: `src/green/interfaces/api/routers/runs.py` (`create_run`)
- Изменить: `src/green/interfaces/api/intake.py` (`accept_street_run`, `_copy_and_execute`)
- Тест: `tests/test_streets.py` (новые тесты на `/api/v1/runs`; старые на `/web/runs` остаются до задачи 13)

**Интерфейсы:**
- Производит: `POST /api/v1/runs` c полями multipart `file?`, `street?`, `profile?`,
  `overrides?`, `inventory?`, `extra[]?`. Ровно один источник: `file` или `street`.
  `accept_street_run(*, container, background, street, profile, overrides, inventory)`.

- [ ] **Шаг 1: падающие тесты** в `tests/test_streets.py`:

```python
def test_api_street_run_goes_all_the_way_to_a_plan(client: TestClient) -> None:
    created = client.post(
        "/api/v1/runs",
        data={"street": "07-test-street", "profile": "strict", "overrides": '{"spacing_m": 6}'},
    )

    assert created.status_code == 202
    record = client.get(f"/api/v1/runs/{created.json()['id']}").json()
    assert record["state"] == "succeeded", record.get("error")
    assert record["summary"]["placements"] > 0
    assert record["source_name"] == "Тестовая улица.dxf"
    assert record["overrides"] == {"spacing_m": 6}


def test_api_refuses_unknown_street(client: TestClient) -> None:
    response = client.post("/api/v1/runs", data={"street": "нет-такой-улицы"})

    assert response.status_code == 422
    assert "нет в каталоге" in response.json()["detail"]


def test_api_run_needs_a_source(client: TestClient) -> None:
    response = client.post("/api/v1/runs", data={"profile": "strict"})

    assert response.status_code == 422
    assert "улицу" in response.json()["detail"]


def test_api_refuses_street_and_file_together(client: TestClient, work: Path) -> None:
    path = work / "own.dxf"
    _street(path)
    response = client.post(
        "/api/v1/runs",
        data={"street": "07-test-street"},
        files={"file": ("own.dxf", path.read_bytes(), "image/vnd.dxf")},
    )

    assert response.status_code == 422
    assert "одно" in response.json()["detail"]
```

- [ ] **Шаг 2:** `uv run pytest tests/test_streets.py -k api -q` - падают (422 от FastAPI: `file` обязателен).
- [ ] **Шаг 3: реализация.** В `create_run`: `file: UploadFile | None = File(None, ...)`,
  `street: str | None = Form(None, description="Улица пилотного проекта из /streets")`.
  Проверки до регистрации прогона: оба источника - `InputError("Укажите что-то одно: улицу
  пилотного проекта или свой чертёж")`; ни одного (или пустое имя файла) -
  `InputError("Выберите улицу пилотного проекта или свой чертёж")`; `street` вместе с `extra` -
  `InputError("У улицы свой комплект файлов: extra с улицей не передаётся")`; улицы нет в
  `container.streets.get(street)` - `InputError(f"Улицы {street} нет в каталоге")`.
  `accept_street_run` принимает `inventory: UploadFile | None`: сохраняет её тем же
  `store_upload` в `inventory{suffix}` и передаёт путь в `_copy_and_execute(container, run_id,
  street, inventory_path)`, который зовёт `container.runs.execute(run_id, inventory_path, extras)`.
- [ ] **Шаг 4:** `uv run pytest tests/test_streets.py -q` - зелёные, включая старые на `/web/runs`.
- [ ] **Шаг 5:** коммит `feat(api): run a pilot street through POST /runs`.

### Задача 2: демо-прогон через JSON API

**Файлы:** изменить `src/green/interfaces/api/routers/runs.py`; тест `tests/test_progress.py`.

**Интерфейсы:** производит `POST /api/v1/runs/demo` -> 202, `RunOut`, заголовок `Location`.

- [ ] **Шаг 1: падающий тест** (рядом с тестом демо через `/web/demo`):

```python
def test_demo_run_through_the_api(client: TestClient) -> None:
    created = client.post("/api/v1/runs/demo")

    assert created.status_code == 202
    run_id = created.json()["id"]
    assert created.headers["location"].endswith(run_id)
    record = client.get(f"/api/v1/runs/{run_id}").json()
    assert record["state"] == "succeeded", record.get("error")
    assert record["summary"]["placements"] > 0
```

- [ ] **Шаг 2:** тест падает (405 или 404).
- [ ] **Шаг 3:** маршрут `@router.post("/demo", status_code=202)` до `/{run_id}`: регистрирует
  `SAMPLE_NAME` с профилем по умолчанию, пишет `write_sample(store.input_path(id))`, ставит
  `container.runs.execute(id, None, ())` в фон, ставит `Location`, возвращает `RunOut`.
- [ ] **Шаг 4:** тест зелёный.
- [ ] **Шаг 5:** коммит `feat(api): demo run of the built-in fragment through the API`.

### Задача 3: размер артефактов в ответе прогона

**Файлы:** `src/green/interfaces/api/schemas.py` (`ArtifactOut`, `RunOut.from_record`),
`src/green/interfaces/api/routers/runs.py`; тест `tests/test_api.py`.

**Интерфейсы:** `ArtifactOut.size_bytes: int | None`; `RunOut.from_record(record, url, size)`,
где `size: Callable[[str, str], int | None]`.

- [ ] **Шаг 1: падающий тест:**

```python
def test_artifacts_carry_their_size(finished: dict[str, object]) -> None:
    sizes = {a["name"]: a["size_bytes"] for a in finished["artifacts"]}

    assert sizes["result.dxf"] > 0
    assert sizes["plan.json"] > 0
```

- [ ] **Шаг 2:** падает (`KeyError: 'size_bytes'`).
- [ ] **Шаг 3:** в роутерах `_artifact_size(container)` возвращает `lambda run_id, name:
  container.store.artifact(run_id, name).stat().st_size`, ошибки `NotFoundError`, `OSError`
  дают `None`.
- [ ] **Шаг 4:** зелёный; коммит `feat(api): artifact sizes in run responses`.

### Задача 4: параметры профиля для формы

**Файлы:** `src/green/interfaces/api/routers/system.py`, `schemas.py`; тест `tests/test_api.py`.

**Интерфейсы:** `GET /api/v1/profiles/{name}` -> `ProfileOut{name: str, spacing_m: float,
modes: list[str], root_barriers: bool, shrub_groups: bool, shrub_rows: bool, curb_hedges: bool,
understory: bool, planting_type: str}`; неизвестный профиль - 404.

- [ ] **Шаг 1: падающие тесты:**

```python
def test_profile_parameters_for_the_form(client: TestClient) -> None:
    strict = client.get(f"{API_PREFIX}/profiles/strict").json()
    shrubs = client.get(f"{API_PREFIX}/profiles/shrubs").json()

    assert strict["spacing_m"] == 5.0
    assert "fill" in strict["modes"]
    assert shrubs["planting_type"] == "shrub"
    assert "fill" not in shrubs["modes"]


def test_unknown_profile_is_not_found(client: TestClient) -> None:
    response = client.get(f"{API_PREFIX}/profiles/nope")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith(PROBLEM_JSON)
```

- [ ] **Шаг 2:** падают (404 без схемы problem, затем - нет маршрута).
- [ ] **Шаг 3:** маршрут: имени нет в `container.profiles.names()` - `NotFoundError`; иначе
  `params = container.profiles.load(name, {})` и `ProfileOut` из полей `PlanParams`.
- [ ] **Шаг 4:** зелёные. `uv run green openapi --out docs/openapi.json`, тест синхрона схемы
  зелёный. Полные Python-гейты. Коммит `feat(api): profile parameters for the run form`.

### Задача 5: каркас `frontend/`

**Файлы (создать):** `frontend/package.json`, `vite.config.ts`, `tsconfig.json`,
`tsconfig.app.json`, `tsconfig.node.json`, `eslint.config.js`, `.prettierrc.json`,
`.prettierignore`, `playwright.config.ts`, `index.html`, `public/mark.svg`,
`src/main.tsx`, `src/App.tsx`, `src/styles/{tokens,fonts,base}.css`, `src/assets/fonts/*.woff2`
(копия из `src/green/interfaces/web/static/fonts`), `src/test/setup.ts`, `.gitignore`
(`node_modules`, `dist`, `test-results`, `playwright-report`).

**Интерфейсы:**
- `npm run dev` - Vite на 5173, прокси `/api` и `/docs` на `GREEN_API_URL` (по умолчанию
  `http://127.0.0.1:8010`).
- `npm run build` - `tsc -b && vite build` в `frontend/dist`; после сборки swagger-ui
  (`swagger-ui-dist`) копируется в `dist/vendor/swagger/`.
- `npm run gen:api` - `openapi-typescript ../docs/openapi.json -o src/api/schema.d.ts`.
- `npm test` - Vitest (jsdom), `npm run e2e` - Playwright.
- Тема: `document.documentElement.dataset.theme = 'light' | 'dark'`, ключ `green-theme` в
  localStorage, выставляется до первой отрисовки скриптом в `index.html` (как в `base.html`).

- [ ] **Шаг 1:** `npm create vite@latest frontend -- --template react-ts`, затем
  `npm i react-router @tanstack/react-query zustand` и
  `npm i -D vitest jsdom @testing-library/react @testing-library/user-event
  @testing-library/jest-dom @playwright/test eslint-plugin-jsx-a11y prettier
  openapi-typescript swagger-ui-dist`.
- [ ] **Шаг 2:** `tsconfig.app.json`: `strict`, `noUncheckedIndexedAccess`,
  `noImplicitOverride`, `verbatimModuleSyntax`. ESLint: `typescript-eslint` strict,
  `react-hooks`, `react-refresh`, `jsx-a11y` recommended.
- [ ] **Шаг 3:** токены. `:root` и тёмная тема из `app.css` переносятся в `tokens.css` без
  изменения имён (`--ok`, `--warn`, `--bad`, `--accent`, `--accent-halo`, `--bone*`,
  `--c-*`, `--grid`, `--sans`, `--mono`, `--fs-*`). `fonts.css` - `@font-face` на локальные
  woff2. `base.css` - сброс, `body`, `.skip`, фокус, кнопки и поля из `app.css`.
- [ ] **Шаг 4:** дымовой тест `src/App.test.tsx`: приложение монтируется, в документе есть
  ссылка «К содержимому» и кнопка «Переключить тему».
- [ ] **Шаг 5:** `npm run typecheck && npm run lint && npm test && npm run build` - зелёные;
  `dist/index.html` и `dist/vendor/swagger/swagger-ui-bundle.js` существуют.
- [ ] **Шаг 6:** коммит `feat(frontend): React + Vite scaffold with the design tokens`.

### Задача 6: чистая логика (`src/lib/`)

**Файлы:** `src/lib/{format,quotes,checks,overrides,warnings,viewHash}.ts` и тесты рядом
`*.test.ts`; фикстура `src/lib/__fixtures__/quotes.golden.json`.

**Интерфейсы:**
- `format.ts`: `meters(v: number): string`, `decimal(v: number): string`,
  `plural(n: number, one: string, few: string, many: string): string`,
  `clockText(s: number): string`, `aboutText(s: number): string`,
  `humanSize(bytes: number): string`, `permille(delta: number): {text: string; zero: boolean}`.
- `quotes.ts`: `clauseNumber(rule: Rule): string`, `quoteOf(rule: Rule): string`,
  `tableQuote(text: string): TableQuote | null`, `listQuote(text: string): ListRow[] | null`.
- `checks.ts`: `CLASS_RU`, `VERDICT_RU`, `KIND_RU`, `whatFor(check, rules): string`,
  `splitChecks(checks): {lead: RuleCheck[]; hidden: RuleCheck[]; restSlack: number | null}`.
- `overrides.ts`: `diffOverrides(profile: ProfileParams, form: RunFormValues, advanced: string):
  Record<string, unknown>` - только отличия формы от профиля, `modes` правится добавлением
  или снятием `fill`, если `advanced` его не задал; некорректный JSON - `Error`.
- `warnings.ts`: `KEY_WARNINGS`, `splitWarnings(list): {notices: string[]; rest: string[]}`.
- `viewHash.ts`: `parseViewHash(hash: string): {x: number; y: number; m: number} | null`.

- [ ] **Шаг 1: тесты-характеристики.** Ожидаемые значения взяты из поведения `plan.js`:

```ts
// format.test.ts
expect(plural(1, 'посадка', 'посадки', 'посадок')).toBe('посадка');
expect(plural(22, 'посадка', 'посадки', 'посадок')).toBe('посадки');
expect(plural(11, 'посадка', 'посадки', 'посадок')).toBe('посадок');
expect(plural(112, 'посадка', 'посадки', 'посадок')).toBe('посадок');
expect(meters(2.5)).toBe('2,50');
expect(clockText(65)).toBe('1:05');
expect(clockText(-3)).toBe('0:00');
expect(aboutText(5)).toBe('несколько секунд');
expect(aboutText(11)).toBe('около 20 с');
expect(aboutText(60)).toBe('около минуты');
expect(aboutText(150)).toBe('около 3 мин');
expect(humanSize(512)).toBe('512 Б');
expect(humanSize(2048)).toBe('2 КБ');
expect(humanSize(3.4 * 1024 * 1024)).toBe('3,4 МБ');

// checks.test.ts
const A = { rule_id: 'A', outcome: 'pass', measured_m: 2.5, threshold_m: 2 };
const B = { rule_id: 'B', outcome: 'pass', measured_m: 10, threshold_m: 2 };
const C = { rule_id: 'C', outcome: 'pass', measured_m: null, threshold_m: 5 };
const D = { rule_id: 'D', outcome: 'pass', measured_m: 3, threshold_m: 2 };
const E = { rule_id: 'E', outcome: 'fail', measured_m: 1, threshold_m: 2 };
expect(splitChecks([A, B, C, D])).toEqual({ lead: [A, D], hidden: [B, C], restSlack: 5 });
expect(splitChecks([A, B, C, D, E])).toEqual({ lead: [E], hidden: [A, B, C, D], restSlack: 1.25 });

// quotes.test.ts
expect(tableQuote('Край проезжей части | 2,0 | 1,0')).toEqual(
  { what: 'Край проезжей части', tree: '2,0 м', shrub: '1,0 м', note: '' });
expect(listQuote('Однорядная | 5-6; Групповая | 5-7')).toEqual(
  [{ what: 'Однорядная', value: '5-6 м' }, { what: 'Групповая', value: '5-7 м' }]);
expect(tableQuote('перечень; строк | 1 | 2')).toBeNull();

// viewHash.test.ts
expect(parseViewHash('#x=9125.5&y=-8905.2&m=0.05')).toEqual({ x: 9125.5, y: -8905.2, m: 0.05 });
expect(parseViewHash('#x=1&y=2')).toEqual({ x: 1, y: 2, m: 0.1 });
expect(parseViewHash('#x=a&y=2')).toBeNull();
expect(parseViewHash('#x=1&y=2&m=0')).toBeNull();
```

- [ ] **Шаг 2: золотой файл цитат.** Скрипт `frontend/scripts/golden-quotes.mjs` вырезает из
  `src/green/interfaces/web/static/plan.js` тела `clauseNumber`, `quoteOf`, `tableQuote`,
  `listQuote`, прогоняет их по всем правилам `rules.json` настоящего прогона и пишет
  `quotes.golden.json` (вход -> выход). Тест `quotes.test.ts` сверяет новую реализацию со всем
  файлом. Расхождение допускается только как осознанная правка с комментарием в тесте
  (кандидат: хвостовая точка у значения «1,5.» перед примечанием).
- [ ] **Шаг 3:** `npm test` - падает (модулей нет). Реализация - перенос функций из
  `plan.js:963-1115`, `1157-1159`, `1944-1954`, `1893-1911` и `_human_size`/`_form_overrides`
  из `pages.py` с типами. `npm test` - зелёный.
- [ ] **Шаг 4:** коммит `feat(frontend): formatting, quotes, checks and overrides logic`.

### Задача 7: клиент API, типы артефактов, запросы

**Файлы:** `src/api/schema.d.ts` (генерируется), `src/api/types.ts`, `src/api/artifacts.ts`,
`src/api/client.ts`, `src/api/queries.ts`, `src/api/client.test.ts`.

**Интерфейсы:**
- `class ApiError extends Error { status: number; title: string; detail: string }` -
  из тела RFC 9457 (`application/problem+json`), иначе из текста ответа.
- `getJson<T>(path): Promise<T>`, `postForm<T>(path, form: FormData): Promise<T>`,
  `postJson<T>(path, body): Promise<T>`; все пути относительные (`/api/v1/...`).
- `artifactUrl(runId, name): string`.
- Хуки: `useMeta()`, `useStreets()`, `useProfile(name)`, `useRuns(limit)`,
  `useRun(id)` - опрос раз в 2 с, пока `state` - `queued` или `running`;
  `useArtifact<T>(runId, name, enabled)` - без повторов на 404.
- `artifacts.ts`: `PlanJson`, `PlacementJson`, `RejectionJson`, `RuleCheck`, `Assortment`,
  `PlantingValue`, `RulesJson`, `Rule`, `QualityJson`, `QualityTerm`, `BasemapJson`,
  `SurfaceMeta` - по `infrastructure/reports/artifacts.py` (`_plan`, `_rules`, `_quality`,
  `_basemap`, `_surface`).

- [ ] **Шаг 1: тест** на `ApiError`: ответ 422 `application/problem+json` c `detail`
  «Улицы x нет в каталоге» даёт `error.detail`; ответ 500 с текстом даёт `error.status === 500`.
- [ ] **Шаг 2:** `npm run gen:api`, реализация, тест зелёный, `npm run typecheck` зелёный.
- [ ] **Шаг 3:** коммит `feat(frontend): typed API client and run queries`.

### Задача 8: консоль запуска (`/`)

**Файлы:** `src/pages/ConsolePage.tsx` (+ `.module.css`), `src/components/TopBar.tsx`,
`src/components/Footer.tsx`, `src/components/console/{RunForm,FileField,RunsRegistry,
ServiceFacts,DemoStart}.tsx` (+ модули стилей), `src/components/icons.tsx`,
`src/components/console/RunForm.test.tsx`.

**Интерфейсы:**
- `RunForm` собирает `FormData`: `street` или `file`, `profile`, `overrides` =
  `JSON.stringify(diffOverrides(profile, values, advanced))` (не отправляется, если пусто),
  `inventory`, `extra`. Отправка: `postForm('/api/v1/runs', ...)`, затем переход на
  `/runs/:id`. Демо: `postJson('/api/v1/runs/demo', {})`, переход.
- Значения формы при выборе профиля берутся из `useProfile(name)`.

- [ ] **Шаг 1: тесты формы** (Testing Library, `fetch` подменён):
  1. выбрана улица - в `FormData` есть `street`, нет `file`;
  2. без улицы и файла - сообщение «Выберите улицу пилотного проекта или свой чертёж.» в
     живой области, запрос не уходит;
  3. профиль не тронут - `overrides` не отправляется;
  4. снята галочка «Добор зоны» у профиля `strict` - `overrides` = `{"modes":["alley","lawn"]}`;
  5. кнопка блокируется на время отправки и пишет «Загружаем чертёж...» / «Готовим улицу...».
- [ ] **Шаг 2:** реализация по `index.html` (разметка, тексты, подсказки) и `pages.py:index`
  (факты: правил, сверено, видов - из `/meta`; последние 12 прогонов - `useRuns(12)`).
  Числа в «Что применяется» набраны `--fs-metric` (правка 3 жюри). Демо показывается, когда
  каталог улиц пуст (как сейчас).
- [ ] **Шаг 3:** тесты зелёные, коммит `feat(frontend): run console with the pilot street catalog`.

### Задача 9: движок карты (`src/map/`)

**Файлы:** `src/map/{types,palette,geometry,chunks,view,render,picking,input,engine}.ts`,
`src/map/view.test.ts`, `src/map/geometry.test.ts`, `src/components/run/PlanMap.tsx`.

**Интерфейсы:**

```ts
export type LayerKey = 'utilities' | 'surfaces' | 'buildings' | 'existing' | 'placements'
  | 'rejections' | 'weak' | 'barrier' | 'surfacemap' | 'labels';
export interface MapItem { kind: 'placement' | 'rejection'; id: string; number: number;
  planting_type: string; x: number; y: number; radius: number; verdict: string;
  species_code?: string; species_ru?: string; species_lat?: string; explanation: string;
  value?: PlantingValue | null; checks: RuleCheck[]; note?: string; barrier_m?: number | null }
export interface EngineHooks {
  select(item: MapItem | null): void;
  probe(item: MapItem, x: number, y: number): void;      // живая проверка точки при переносе
  move(item: MapItem, x: number, y: number): void;       // отпущено: правка
  remove(item: MapItem): void;                           // Delete в режиме правки
  viewChanged(): void;                                   // для ползунка масштаба
}
export class PlanEngine {
  constructor(canvas: HTMLCanvasElement, root: HTMLElement, hooks: EngineHooks);
  setBasemap(basemap: BasemapJson): void;
  setPlan(placements: MapItem[], rejections: MapItem[]): void;
  setSurface(surface: SurfaceImage | null): void;
  setLayers(visible: Record<LayerKey, boolean>): void;
  setSpeciesOff(codes: ReadonlySet<string>): void;
  setHighlight(code: string | null): void;
  setSelected(item: MapItem | null): void;
  setEditing(on: boolean): void;
  setDragVerdict(verdict: string | null): void;
  fit(): void; zoomBy(factor: number): void;
  zoomShare(): number; setZoomShare(share: number): void;
  orientation(): 'street' | 'north'; toggleOrientation(): void;
  step(delta: number): void; centerSelected(): void;
  applyHash(hash: string): boolean; saveView(key: string): void; restoreView(key: string): boolean;
  repaint(): void; resize(): void; destroy(): void;
}
```

Панели, которые накрывают карту, помечаются `data-map-obstacle="left|right|bottom|top"`;
`clearArea` считает свободную область по ним внутри `root` (перенос `plan.js:326-359`).

Соответствие функций `plan.js` модулям:

| `plan.js` | модуль |
|---|---|
| `STYLES`, `VERDICT_TOKEN`, `css` (19-54, 141-151) | `palette.ts` |
| `addRing`, `addGeometry`, `measure`, `principalAxis`, `contentPoints`, `trimmed`, `geometryPoints`, `boundsOfPoints` | `geometry.ts` |
| `GRID`, `BANDS`, `buildChunks` (210-288) | `chunks.ts` |
| `toView`, `toScreen`, `worldBounds`, `viewExtent`, `fitToBbox`, `zoomBounds`, `zoomAt`, `keepView`, `toWorld`, `panTo`, `revealSelected`, `centerSelected` | `view.ts` + `engine.ts` |
| `renderBase`, `drawLabels`, `uncovered`, `draw`, `drawGrid`, `niceLength`, `drawScaleBar`, `drawPlacements`, `drawRejections`, `isWeak`, `drawWeak`, `drawBarrierPlaces`, `ring`, `drawSelection`, `drawNorth` | `render.ts` |
| `pick`, `shown`, `orderItems`, `step` | `picking.ts` |
| `bindInput` (1524-1618) | `input.ts` |
| `loadSurface`, `showDrawing`, `mount`, `restoreView`, `viewFromHash`, `rememberView` | `engine.ts` + `PlanMap.tsx` |

Правка «вписать» (жюри, правка 1): вид по умолчанию вписывает план так, чтобы лента по
короткой стороне занимала не меньше 55% высоты свободной области; если план при этом не
влезает по длине, вид центрируется на середине плана, остальное доступно панорамой. Кнопка
«вписать» показывает план целиком.

- [ ] **Шаг 1: тесты чистой геометрии** (`view.test.ts`, `geometry.test.ts`):
  `toWorld(toScreen(p)) ≈ p` при произвольном развороте и масштабе; `principalAxis` для точек на
  прямой под 30° даёт 30°; `trimmed` отбрасывает выброс за 2-98 процентилем; `niceLength(137)
  === 100`, `niceLength(260) === 200`, `niceLength(0.7) === 0.5`; `fitBox` для ленты 600 x 100
  в области 1000 x 500 при правиле «короткая сторона 55%» даёт масштаб 2,75.
- [ ] **Шаг 2:** перенос модулей по таблице; `PlanMap.tsx` создаёт движок в `useEffect` и
  уничтожает в очистке (StrictMode монтирует дважды: `destroy` снимает все обработчики,
  `ResizeObserver`, `MutationObserver` темы, таймеры и кадры анимации).
- [ ] **Шаг 3:** тесты зелёные, `npm run typecheck`, коммит `feat(frontend): canvas plan engine ported from plan.js`.

### Задача 10: рабочее место прогона (`/runs/:id`)

**Файлы:** `src/pages/RunPage.tsx` (+ `.module.css`), `src/state/workspace.ts`,
`src/components/run/{RunHeader,RunMetrics,Notices,WarningsFold,ProgressHud,RunStatus,MapHud,
Legend,Downloads,PanelToggle}.tsx` (+ стили).

**Интерфейсы:**
- `useWorkspace` (Zustand): `selected`, `layers: Record<LayerKey, boolean>` (как
  `state.visible` в `plan.js`), `speciesOff: Set<string>`, `highlight`, `editing`, `stale`,
  `message: {text; kind}`, `panels: {left; right; legend}` (сохраняются в localStorage под
  прежними ключами `green-panel-left|right`, `green-legend`).
- Пока прогон `queued|running`: `ProgressHud` из `run.progress`, часы тикают раз в секунду
  локально; как только в `artifacts` появляется `basemap.geojson` - подоснова на карте. Когда
  прогон кончился - данные прогона перезапрашиваются без перезагрузки страницы, вид
  сохраняется.
- `failed`: причина из `run.error`.

- [ ] **Шаг 1:** компонентные тесты: `Notices` выносит предупреждения из `KEY_WARNINGS` в
  сводку, остальные - в свёрнутый список с числом; `ProgressHud` для `queued` пишет «В очереди»
  и «ждём свободного места»; `Downloads` показывает `result.dxf` и `interpretations.csv`
  первыми, служебные файлы - свёрнутыми, с размером из `size_bytes`.
- [ ] **Шаг 2:** реализация по `run.html` и `_run_status.html`, стили по `app.css`
  (`.workspace`, `.hud*`, `.legend*`, `.metric*`, `.notice`, `.fold`, `.downloads`).
- [ ] **Шаг 3:** зелёные тесты; коммит `feat(frontend): run workspace with progress, legend and downloads`.

### Задача 11: панель посадки, состава и качества

**Файлы:** `src/components/detail/{DetailPanel,PlacementDetail,ChecksBlock,CheckRow,
QuoteBlock,ValueBlock,BarrierBlock,QualityBlock,Composition}.tsx` (+ стили), тесты
`ChecksBlock.test.tsx`, `QuoteBlock.test.tsx`, `ValueBlock.test.tsx`.

**Интерфейсы:** `DetailPanel` без выбора - `QualityBlock` + `Composition` (галочка вида,
подсветка кликом, «показать все»); с выбором - `PlacementDetail` (перенос `showDetail`,
`checksBlock`, `checkRow`, `quoteBlock`, `valueBlock`, `barrierBlock` - `plan.js:1044-1325`).

- [ ] **Шаг 1: тесты:** нарушенная норма печатается под заголовком «Нарушено»; без нарушений -
  «Ближе всего к норме» и строка «Проверено ещё N норм, наименьший запас у них - K-кратный»;
  правила без замера не печатаются, но входят в счёт; цитата табл. 9.1 разбирается на «до ствола
  дерева» и «до кустарника»; перечень табл. 3.6.2 - списком; отрицательный вклад со `flagged`
  даёт «Слабое место».
- [ ] **Шаг 2:** реализация; тексты - как в `plan.js`, длинное тире заменено.
- [ ] **Шаг 3:** зелёные; коммит `feat(frontend): planting, composition and quality panels`.

### Задача 12: правка плана

**Файлы:** `src/components/run/EditBar.tsx`, `src/state/editQueue.ts`,
`src/state/editQueue.test.ts`.

**Интерфейсы:**
- `EditQueue` - правки уходят на сервер строго по одной: следующая ждёт ответа на предыдущую
  (гонка из аудита: одновременные правки терялись). `enqueue(edit): Promise<PlanSummary>`.
- Перенос: живая проверка `POST /check` с отбросом устаревших ответов по номеру запроса
  (как `probeTicket`), после отпускания - `POST /edits`, затем `POST /check` для обновления
  вердикта и трассы. Удаление - Delete в режиме правки.
- Пересборка: `POST /rebuild`, затем опрос `GET /runs/:id` до конца пересборки
  (`summary.stale === false` и состояние не `running`); сообщение «пересобраны» - только
  после этого; при ошибке кнопка снова доступна и показана причина.

- [ ] **Шаг 1: тест очереди:** две правки подряд, первая отвечает позже второй - на сервер они
  приходят по порядку, вторая стартует после ответа на первую, обе обещания выполняются.
- [ ] **Шаг 2:** реализация; коммит `feat(frontend): sequential edits and honest rebuild status`.

### Задача 13: переключение раздачи и удаление Jinja2

**Файлы:**
- Создать: `src/green/interfaces/web/spa.py`; тест `tests/test_spa.py`.
- Изменить: `src/green/interfaces/api/app.py`, `src/green/bootstrap/settings.py`
  (`web_dir: Path = Path("frontend/dist")`), `src/green/interfaces/web/__init__.py`,
  `pyproject.toml` (`uv remove jinja2`; per-file-ignores для `web`), `tests/test_streets.py`,
  `tests/test_progress.py` (перевод с `/web/*` на API).
- Удалить: `src/green/interfaces/web/pages.py`, `templates/`, `static/`, `tests/test_web.py`.

**Интерфейсы:** `mount_spa(app: FastAPI, web_dir: Path) -> None`; `/docs` со swagger-ui из
`web_dir/vendor/swagger`, если он есть; `redoc_url=None`.

- [ ] **Шаг 1: тесты `test_spa.py`** на временном каталоге-бандле: `/` и `/runs/abc` отдают
  `index.html`; `/assets/app.js` отдаёт файл; `/assets/missing.js` - 404; `/api/v1/health` не
  перехватывается; без бандла `/` - 503 с текстом про `npm run build`, `/api/v1/health` - 200;
  `/docs` при наличии `vendor/swagger` ссылается на `/vendor/swagger/swagger-ui-bundle.js` и не
  содержит `cdn.jsdelivr.net`.
- [ ] **Шаг 2:** реализация, перевод старых тестов на API, удаление Jinja2. Полные
  Python-гейты, `docs/openapi.json` пересобран.
- [ ] **Шаг 3:** коммит `refactor(web)!: serve the React bundle, drop Jinja2 pages` с
  `BREAKING CHANGE: веб-маршруты /web/runs, /web/demo, /runs/{id} (HTML) и /static удалены`.

### Задача 14: Docker

**Файлы:** `docker/Dockerfile` (стадия `web`), `.dockerignore`, `docs/deploy.md`.

- [ ] **Шаг 1:** стадия `FROM node:24-slim AS web`: `npm ci`, `npm run build` в `/web`;
  в рабочем образе `COPY --from=web /web/dist /app/web`, `ENV GREEN_WEB_DIR=/app/web`.
  `.dockerignore`: `frontend/node_modules`, `frontend/dist`, `frontend/test-results`,
  `frontend/playwright-report`.
- [ ] **Шаг 2:** `docker build -f docker/Dockerfile -t green:react .`; контейнер на порту 8011:
  healthy; `/` отдаёт интерфейс; демо проходит через интерфейс; `/docs` открывается с
  отключённой сетью контейнера (`--network none` после старта не нужен: проверка - в HTML
  `/docs` нет внешних адресов).
- [ ] **Шаг 3:** коммит `build(docker): build the React bundle in a node stage`.

### Задача 15: проверка фронта целиком

- [ ] **Шаг 1:** Playwright `e2e/demo.spec.ts` на живом бэкенде (порт 8012, личность по
  `/api/v1/meta`): консоль -> демо -> ожидание готовности -> канва нарисована (пиксели не
  пустые) -> клик по посадке -> в панели есть `R-`, акт и «п.» -> режим правки, перенос ->
  сообщение «перенесена» -> пересборка -> «пересобраны» -> ссылка `result.dxf` отдаёт 200.
  Все запросы страницы - только на `127.0.0.1:8012` (`page.on('request')`).
- [ ] **Шаг 2:** скриншоты `playwright-cli`: консоль и рабочее место, 1440, 1100, 390, светлая
  и тёмная тема, выбранная посадка, режим правки, сообщение правки; просмотреть глазами.
- [ ] **Шаг 3:** `accesslint:accessibility-scan` по живым страницам; `web-design-guidelines`
  по коду; всё найденное - исправить.
- [ ] **Шаг 4:** замер кадра на Кустанайской: перетаскивание карты, `performance` в браузере,
  кадр не дольше 16 мс.
- [ ] **Шаг 5:** агент `design-jury` - до PASS; вердикт в `docs/design-reviews/iteration-4.md`.
- [ ] **Шаг 6:** коммиты по найденному, `fix(frontend): ...`.

### Задача 16: документация и пуш

**Файлы:** `CLAUDE.md` (карта: `frontend/`, запуск), `README.md` (сборка фронта, разработка),
`docs/notes/31-react-frontend.md` (что перенесено, что исправлено, замеры), `docs/demo.md`,
`docs/notes/25-web-ui.md` (пометка: интерфейс перенесён на React).

- [ ] **Шаг 1:** документы; полные гейты Python и фронта.
- [ ] **Шаг 2:** коммит `docs: React frontend in the map, notes and demo`.
- [ ] **Шаг 3:** `git push -u origin feat/react-frontend`.
