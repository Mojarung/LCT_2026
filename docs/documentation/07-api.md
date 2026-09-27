## 7. HTTP API и Swagger {#api}

Swagger UI: `http://<хост>:8000/docs`, статика из образа, без CDN. Схема OpenAPI 3.1:
`/api/v1/openapi.json`, в репозитории - `docs/openapi.json`. Совпадение файла с кодом
проверяет тест `test_committed_openapi_file_matches_the_code`. Каждый метод можно вызвать из
Swagger UI («Try it out») без чтения кода: у полей формы и параметров есть описания.

### 7.1. Методы

| Метод | Путь | Назначение |
|---|---|---|
| GET | `/api/v1/health` | состояние сервиса и версия |
| GET | `/api/v1/meta` | профили, правила, акты, виды: числа для интерфейса |
| GET | `/api/v1/profiles/{name}` | параметры профиля |
| GET | `/api/v1/streets` | каталог улиц пилота |
| POST | `/api/v1/runs` | поставить прогон: `file` (DXF или DWG) или `street`; `profile`, `overrides` (JSON), `extra` (чертежи комплекта), `inventory` (перечётная ведомость), `layers` (слои ГИС) |
| POST | `/api/v1/runs/demo` | прогон на встроенном фрагменте улицы |
| GET | `/api/v1/runs` | реестр прогонов |
| GET | `/api/v1/runs/{run_id}` | статус: `state`, этап и доля, `summary`, список артефактов с адресами и размерами |
| GET | `/api/v1/runs/{run_id}/artifacts/{name}` | файл прогона: `result.dxf`, `interpretations.csv`, `report.html` и др. (приложение C) |
| POST | `/api/v1/runs/{run_id}/check` | проверка точки `{x, y, species}` теми же нормами: вердикт, трасса правил |
| GET | `/api/v1/runs/{run_id}/draft` | текущий черновик плана после правок и признак «не пересобран» |
| POST | `/api/v1/runs/{run_id}/edits` | правки: `move`, `delete`, `add` |
| POST | `/api/v1/runs/{run_id}/rebuild` | пересборка DXF и артефактов по черновику |

### 7.2. Пример

```bash
# 1. Поставить прогон
curl -s -F "file=@street.dxf" -F "profile=strict" -F 'overrides={"sp42_edition": "2026"}' \
     http://localhost:8000/api/v1/runs
# {"id": "01a0dfb1-...", "state": "queued", ...}, заголовок Location: /api/v1/runs/01a0dfb1-...

# 2. Дождаться succeeded
curl -s http://localhost:8000/api/v1/runs/01a0dfb1-...
# {"state": "succeeded", "summary": {"placements": 861, "allowed": 838, "needs_approval": 23,
#   "rejections": 425, "integrity_ok": true, "plan_valid": true, "export_matches_plan": true, ...},
#  "artifacts": [{"name": "result.dxf", "url": "...", "size_bytes": ...}, ...]}

# 3. Проверить точку перед правкой
curl -s -X POST -H "content-type: application/json" \
     -d '{"x": 16046.25, "y": -5738.63, "species": "acer_ginnala"}' \
     http://localhost:8000/api/v1/runs/01a0dfb1-.../check
# {"verdict": "allowed", "plantable": true, "checks": [{"rule_id": "R-BLD-TREE-001",
#   "outcome": "pass", "measured_m": 22.19, "threshold_m": 5.0, ...}, ...]}
```

### 7.3. Ошибки

Ошибки возвращаются в формате RFC 9457 (`application/problem+json`): `title` - стандартная
фраза статуса HTTP («Not Found»), `status` - код, `detail` - причина на русском языке,
`instance` - путь запроса, у ошибок валидации - `errors` с полями запроса.

| Код | Когда |
|---|---|
| 400 | прочая ошибка входных данных сервиса без отдельного кода |
| 404 | нет прогона или артефакта |
| 409 | правка прогона, контекст которого не сохранён (прогон не закончен, сделан прежней версией сервиса или удалён) |
| 413 | файл больше `GREEN_MAX_UPLOAD_MB` (512 МБ) |
| 422 | некорректные параметры или JSON переопределений, файл не того типа, неверное тело запроса |
| 500 | ошибка конфигурации сервиса |

Отказы самого прогона возникают в фоновом расчёте, поэтому приходят не кодом HTTP, а статусом
`state: failed` с причиной в поле `error`. Причины: неполное чтение геометрии, неопределённые
классы, не заданные единицы чертежа, неудачная конвертация DWG, проверка плана или DXF. Нет
границы работ - не остановка: прогон заканчивается пустым планом, в предупреждениях сказано,
что границы нет. Прогон, прерванный остановкой
сервиса, читается как `failed` с причиной «Прогон прерван».
