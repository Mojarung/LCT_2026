# green

Сервис автопроектирования озеленения улиц для кейса ДПиООС (ЛЦТ 2026): DXF или DWG с подосновой и сетями -> ограничения по нормам -> план посадок на отдельных слоях `GREEN_*` -> DXF и файл объяснений со ссылками на правила и пункты НПА. Исходные слои не меняются, это проверяется на каждом прогоне.

```bash
uv sync
uv run green run путь/к/файлу.dxf --profile strict
uv run green run путь/к/файлу.dxf --inventory перечётка.xls   # существующие деревья в квотах
uv run green serve                  # OpenAPI: http://127.0.0.1:8000/docs
docker compose up --build           # то же в контейнере, API на :8000
```

Вид для каждой посадки подбирается сервисом: жёсткие фильтры по нормам (369-ПП, 743-ПП п. 3.6.18, отступы по роду, крона шире 5 м, высота под ВЛ) и по справочнику (морозостойкость, реагенты), затем оценка пригодности в процентах и назначение с жёсткими квотами разнообразия 10-20-30. Перечётная ведомость через `--inventory` добавляет в квоты уже растущие деревья. База видов — [config/species.yaml](config/species.yaml), её описание — [docs/species.md](docs/species.md).

Артефакты прогона: `result.dxf`, `plan.json`, `interpretations.csv` и `.json`, `assortment.json` (состав плана: доли, разнообразие, сезонность), `zones.geojson`, `run_manifest.json`, `verify.json`, `layers_report.json`.

Линтеры и тесты: `uv run ruff check src tests`, `uv run ruff format --check src tests`, `uv run ty check src`, `uv run lint-imports`, `uv run pytest`.

Подробности: [docs/architecture.md](docs/architecture.md), алгоритм по шагам: [docs/algorithm.md](docs/algorithm.md), база видов: [docs/species.md](docs/species.md), разбор ресерча: [docs/research-review.md](docs/research-review.md).
