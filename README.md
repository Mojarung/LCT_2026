# green

Сервис автопроектирования озеленения улиц для кейса ДПиООС (ЛЦТ 2026). На входе DXF или DWG с
подосновой Мосгеотреста и сетями. Сервис строит ограничения по нормам (СП 42.13330, 743-ПП,
623-ПП / МГСН 1.02-02, 369-ПП), расставляет деревья и кустарник и возвращает DXF: исходные слои
без изменений, план - на отдельных слоях `GREEN_*`. У каждой посадки и каждого отказа есть
объяснение с актом и пунктом нормы: атрибутом в DXF и отдельными файлами (CSV, JSON, Markdown,
HTML-отчёт).

## Запуск

В Docker (целевая среда - МосТех.ОС или совместимый Linux):

```bash
docker compose up --build -d          # интерфейс и API на http://localhost:8000/
curl -s http://localhost:8000/api/v1/health
```

Swagger - `http://localhost:8000/docs`, схема - [docs/openapi.json](docs/openapi.json).
Kubernetes по желанию: `kubectl apply -k deploy/k8s`.

Без Docker (Python 3.14, [uv](https://docs.astral.sh/uv/)):

```bash
uv sync
uv run green run путь/к/файлу.dxf --profile strict             # DXF или DWG
uv run green run генплан.dxf сети.dxf покрытия.dxf              # комплект склеивается в один чертёж
uv run green run путь/к/файлу.dxf --inventory перечётка.xls     # существующие деревья в квотах
uv run green run путь/к/файлу.dxf --set spacing_m=6             # любой параметр профиля
uv run green verify вход.dxf out/<прогон>/result.dxf            # исходные сущности не изменены
uv run green audit план.dxf --plantings "^0?6_+ДП_.+_план$"     # нормоконтроль чужого плана
(cd frontend && npm ci && npm run build) && uv run green serve  # веб-интерфейс на :8000
```

Профили норм - `config/profiles/`: `strict` (по умолчанию), `barriers` (прикорневые барьеры,
СП 42, табл. 9.1, прим. 5), `no_utilities` (съёмка без сетей), `review` (незнакомый DXF без
эвристик классов), `shrubs`. Все параметры - приложение D документации.

## Документация

- [docs/documentation/](docs/documentation/) и её сборка
  [green-documentation.pdf](docs/documentation/green-documentation.pdf): назначение и границы
  ([01](docs/documentation/01-scope.md)), архитектура и развёртывание
  ([02](docs/documentation/02-architecture.md)), алгоритм, интерпретируемость и BPMN
  ([03](docs/documentation/03-algorithm.md)), методы и библиотеки
  ([04](docs/documentation/04-methods.md)), сборка, запуск и проверка
  ([05](docs/documentation/05-run.md)), способы работы ([06](docs/documentation/06-interaction.md)),
  API ([07](docs/documentation/07-api.md)), ограничения и известные ошибки
  ([08](docs/documentation/08-limitations.md)); приложения - свод правил, итоги по улицам
  пилота, файлы прогона, параметры ([generated/](docs/documentation/generated/)).
- Презентация: [docs/presentation.pdf](docs/presentation.pdf), живая версия с анимацией -
  [docs/presentation.html](docs/presentation.html).
- Сценарий демонстрации: [docs/demo.md](docs/demo.md).
- Требования к посадке по актам заказчика и цитаты норм:
  [docs/requirements/](docs/requirements/planting-requirements.md); база видов -
  [docs/species.md](docs/species.md).

## Пример входа и выхода

[examples/](examples/README.md): фрагмент улицы Берзарина, `result.dxf` со слоями `GREEN_*`,
отчёт интерпретаций, CSV посадок, проверка целостности и снимки 3D-вида участка.

## Проверки

```bash
uv run pytest
uv run ruff check src tests && uv run ruff format --check src tests
uv run ty check src && uv run lint-imports
cd frontend && npm test
```

Датасет пилота и тексты ТЗ в репозиторий не входят: `dataset/` монтируется в контейнер как
`/dataset` (разд. 5.2 документации).
