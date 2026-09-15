# LCT_2026: указатели для работы с проектом

Пакет `green` строит план посадок из DXF/DWG на отдельных слоях `GREEN_*` с трассой нормативных правил. Структура кода — в [docs/architecture.md](docs/architecture.md), **действующий алгоритм** — в [docs/algorithm.md](docs/algorithm.md). Для новой задачи сначала сверяйте эти документы с текущим кодом и конфигом.

| Нужна информация | Где основной источник |
|---|---|
| Требования кейса и пробелы | [docs/spec.md](docs/spec.md), затем [docs/plan.md](docs/plan.md) |
| Слои, входные данные и CAD-пакеты | [docs/notes/08-dataset-map.md](docs/notes/08-dataset-map.md), [docs/notes/05-dwg-scan.md](docs/notes/05-dwg-scan.md) |
| Действующие правила и статус цитат | `config/rules.yaml`, [docs/notes/07-norms.md](docs/notes/07-norms.md) |
| Результаты прошлых прогонов и ошибки | [docs/notes/04-issues-and-fixes.md](docs/notes/04-issues-and-fixes.md) |
| Принятые решения и внешние методы | [docs/notes/03-decisions.md](docs/notes/03-decisions.md), [docs/research-review.md](docs/research-review.md) |

Исходный PDF ТЗ и датасет находятся локально вне Git; в репозиторий не добавлять чертежи, персональные таблицы и результаты прогонов. Команды запуска и проверки перечислены в [README.md](README.md), зависимости — в `pyproject.toml` и `uv.lock`. Не считайте исторический результат прогона новой проверкой: указывайте файл, дату, версию и предел проверки. `verify.ok` подтверждает сохранность экспортируемых DXF-сущностей, но не пригодность грунта, правильность норм или полноту исходного DWG.
