# Тесты HTTP API и выгрузка OpenAPI (18.09.2026)

Swagger при наличии бэкенда - обязательное условие сдачи и строка в критериях. До этого шага у API не было ни одного теста: работоспособность проверялась руками в контейнере (`notes/10-assortment-runs.md`).

## Шаг 1. Тесты

`tests/test_api.py`, 22 теста. Клиент - `fastapi.testclient.TestClient`: фоновую задачу он выполняет до возврата ответа, поэтому после `POST /runs` прогон уже завершён и опрашивать статус не нужно. Чертёж - синтетическая улица из `test_pipeline_synthetic.py`.

| Что проверяется | Тест |
|---|---|
| `/health`, `/meta`: профили, число правил, слои результата, виды | `test_health_and_meta_describe_the_service` |
| Схема OpenAPI содержит все пять маршрутов, форму загрузки и ответы с ошибками; `/docs` открывается | `test_openapi_documents_every_route` |
| `docs/openapi.json` в репозитории совпадает со схемой из кода | `test_committed_openapi_file_matches_the_code` |
| Полный цикл: 202 и заголовок `Location`, статус `succeeded`, сводка, список артефактов | `test_run_succeeds_and_lists_artifacts` |
| Скачанный `result.dxf` читается ezdxf, вставок на `GREEN_TREES` столько же, сколько посадок `allowed` в `plan.json`; ведомость отдаётся как `text/csv` | `test_artifacts_download_and_match_the_summary` |
| Комплект из двух чертежей через поле `extra` склеивается | `test_kit_of_two_drawings_is_merged` |
| Битый JSON в `overrides`, не объект, значение вне границ, неизвестный параметр, неизвестный профиль: 422 и прогон не создаётся | `test_bad_parameters_are_refused_before_the_run` |
| Запрос без файла: 422 со списком `errors` | `test_request_without_a_file_is_a_validation_problem` |
| В `extra` не чертёж: 422 | `test_extra_file_that_is_not_a_drawing_is_refused` |
| Файл больше лимита: 413, прогон записан как `failed` | `test_upload_over_the_limit_is_refused_and_recorded` |
| Файл не DXF: прогон принят, завершается `failed` с причиной, артефактов нет | `test_broken_drawing_fails_the_run_with_a_reason` |
| Неизвестный прогон, чужой артефакт, обход каталога (`..%2F`, `%2E%2E%5C`): 404 | `test_unknown_runs_and_artifacts_are_not_found` |
| Ошибки самого фреймворка в том же формате | `test_framework_errors_use_the_same_format` |

## Шаг 2. Что нашли тесты

Ответ на путь `/runs/<id>/artifacts/..%2F..%2Fpyproject.toml` приходил как `application/json` с телом `{"detail": "Not Found"}`. Файл при этом не отдавался: `%2F` раскрывается в `/`, маршрут не совпадает, отвечает Starlette. Но формат ошибки расходился с заявленным RFC 9457. Правка: в `interfaces/api/errors.py` добавлен обработчик `StarletteHTTPException`, теперь 404 маршрута и 405 метода приходят как `application/problem+json`, заголовки фреймворка (`Allow`) сохраняются.

Неизвестный профиль даёт 422, а не 404: профиль - параметр запроса, а не ресурс.

## Шаг 3. Зависимость

`TestClient` требует HTTP-клиент. Starlette 1.6.0 с `httpx` выдаёт `StarletteDeprecationWarning: Using httpx with starlette.testclient is deprecated; install httpx2 instead` (`starlette/testclient.py:48`). В dev-группу добавлен `httpx2>=2.13.0`:

```
uv add --dev httpx2
```

В образ сервиса он не попадает: это зависимость тестов.

## Шаг 4. Выгрузка схемы

Команда `green openapi` печатает схему или пишет её в файл. Ключи отсортированы, поэтому файл меняется только вместе с API.

```
uv run green openapi --out docs/openapi.json
```

`docs/openapi.json` (19 КБ) лежит в репозитории для сдачи и для клиентов, которым не нужен запущенный сервис. Тест из шага 1 не даёт файлу отстать от кода.

## Проверка

```
uv run pytest tests/test_api.py -q
# 22 passed
GREEN_LAWS_DIR="<папка с актами>" uv run pytest -q
# 180 passed
```

Раньше один тест пропускался: `test_real_berzarina_survey_is_read` искал перечётку в `dataset/streets/`, а на этой машине датасет распакован в `dataset/Датасет/`. Теперь тест проверяет обе папки и пропускается, только если датасета нет вовсе.
