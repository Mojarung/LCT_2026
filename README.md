# green

Сервис автопроектирования озеленения улиц для кейса ДПиООС (ЛЦТ 2026): DXF или DWG с подосновой и сетями -> ограничения по нормам -> план посадок на отдельных слоях `GREEN_*` -> DXF и файл объяснений со ссылками на правила и пункты НПА. Исходные слои не меняются, это проверяется на каждом прогоне.

```bash
uv sync
uv run green run путь/к/файлу.dxf --profile strict
uv run green serve                  # OpenAPI: http://127.0.0.1:8000/docs
docker compose up --build           # то же в контейнере, API на :8000
```

Линтеры и тесты: `uv run ruff check src tests`, `uv run ruff format --check src tests`, `uv run ty check src`, `uv run lint-imports`, `uv run pytest`.

Подробности: [docs/architecture.md](docs/architecture.md), алгоритм по шагам: [docs/algorithm.md](docs/algorithm.md), разбор ресерча: [docs/research-review.md](docs/research-review.md).
