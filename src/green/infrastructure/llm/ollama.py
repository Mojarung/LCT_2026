"""Подсказка класса слоя по имени через Ollama (локальная LLM).

Промпт - из опыта E1 (tools/research/ml/exp_names.py): список классов сервиса с пояснением и
общие соглашения имён московских чертежей. Формат ответа исполняет код (parse_rows): номер
строки, класс, уверенность 0..1; всё прочее отбрасывается, класс сверяет вызывающий
(application/name_hints.py). Сбой запроса - исключение: вызывающий решает, что сказать.
"""

from __future__ import annotations

import http.client
import json
import time
import urllib.request
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

CLASS_TEXT = {
    "building": "здание, жилой дом, строение",
    "school": "здание школы или детского сада",
    "structure": "сооружение: подпорная стенка, парапет, павильон, остановка, мост, шахта",
    "obstacle": (
        "малая форма и препятствие: МАФ, скамья, урна, вазон, павильон, детское и спортивное "
        "оборудование, лестница"
    ),
    "fence": "ограждение, забор",
    "curb": "бортовой камень (бордюр), край проезжей части линией",
    "pavement_edge": "граница двух покрытий линией: «граница покрытия», «край площадки»",
    "road": "проезжая часть, парковка, проезд (покрытие)",
    "sidewalk": (
        "тротуар, дорожка, площадка с твёрдым покрытием; и просто материал покрытия: плитка, "
        "асфальт, резиновая крошка, щебень, ПГС, песок"
    ),
    "lawn": "газон, цветник, озеленённая поверхность",
    "existing_tree": "существующее дерево (TREE, деревья, дендро)",
    "existing_shrub": "существующий кустарник (BUSH, кустарники)",
    "existing_woodland": "массив существующих насаждений",
    "pole": "опора освещения, столб (STOLB), фонарь, светофор",
    "utility.access": "колодец, люк, камера, дождеприёмник",
    "utility.water": "водопровод",
    "utility.sewer": "канализация",
    "utility.storm": "водосток, ливневая канализация",
    "utility.drain": "дренаж",
    "utility.heat": "теплосеть",
    "utility.gas": "газопровод",
    "utility.power_cable": "кабель силовой (электроснабжение, наружное освещение)",
    "utility.telecom": "кабель связи",
    "utility.unknown": "подземная сеть неизвестного вида, труба, футляр",
    "power_line_overhead": "воздушная линия электропередачи",
    "slope": "откос",
    "railway": "железная дорога",
    "tram": "трамвайные пути",
    "work_boundary": "граница работ, граница участка благоустройства",
    "contour": "линия съёмки без определённого смысла",
    "ignore": (
        "оформление листа: тексты, номера, размеры, выноски, рамки, разметка, условные обозначения"
    ),
}
KNOWLEDGE = """Соглашения в именах слоёв московских чертежей:
- Префиксы проектов ДВ_ГП (генплан), ДВ_ПП (план покрытий): ПЧ - проезжая часть (road), ТР/трот
  - тротуар (sidewalk).
- «сущ.» - существующий объект того же вида.
- Растения (TREE, BUSH, деревья, кустарники, породы) - существующие деревья и кустарники, это не
  газон.
- Колодец, люк, камера, решётка, ДК, СК - utility.access, даже если названа сеть.
- Горизонтали, отметки, пикеты, размеры, выноски, рамки, номера, подписи, условные обозначения,
  TXT, скрытые и вспомогательные слои - ignore.
- Демонтаж - объекта не будет: ignore. «Замена», «ремонт», «устройство», «контур», «штриховка» -
  класс по самому объекту («Контур парковки» - road, «Штриховка газона» - lawn).
- Номер в начале имени («2.Плитка», «05STOLB», «24_...») - код раздела, класс по словам после
  него.
- Если в имени несколько объектов через «и» или «_», класс по первому из сетей и покрытий.
- Имена бывают латиницей и транслитом русских слов: переводи их по смыслу (DOROGA - край дороги
  линией, curb; ZABOR - fence).
- Газон и граница работ решают, ГДЕ сажать: назначай их только при прямом слове (газон, цветник,
  граница работ, BOUND, LAWN, FLOWER); иначе другой класс."""
SCHEMA = {
    "type": "object",
    "properties": {
        "rows": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "cls": {"type": "string", "enum": [*CLASS_TEXT, "unknown"]},
                    "confidence": {"type": "number"},
                },
                "required": ["id", "cls", "confidence"],
            },
        }
    },
    "required": ["rows"],
}


def parse_rows(text: str) -> dict[int, tuple[str | None, float]]:
    """Строки ответа по номеру имени: класс (None для unknown) и уверенность в 0..1. Ответ без
    JSON - пусто: такие имена остаются без подсказки."""
    text = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    start = min((i for i in (text.find("["), text.find("{")) if i >= 0), default=-1)
    if start < 0:
        return {}
    try:
        data = json.JSONDecoder().raw_decode(text[start:])[0]
    except json.JSONDecodeError:
        return {}
    rows = data.get("rows", []) if isinstance(data, dict) else data
    out: dict[int, tuple[str | None, float]] = {}
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict) or "id" not in row or "cls" not in row:
            continue
        head = str(row["id"]).split(".", 1)[0].strip()
        if not head.isdigit():
            continue
        cls = str(row["cls"]).strip()
        try:
            confidence = float(row.get("confidence") or 0.0)
        except TypeError, ValueError:
            confidence = 0.0
        out[int(head)] = (None, 0.0) if cls == "unknown" else (cls, min(max(confidence, 0.0), 1.0))
    return out


class OllamaNameHinter:
    """Ollama /api/chat с JSON-схемой, без рассуждений, температура 0, партиями имён."""

    def __init__(self, url: str, model: str, *, timeout_s: float = 120.0, batch: int = 25) -> None:
        self._url = url.rstrip("/")
        self._model = model
        self._timeout = timeout_s
        self._batch = batch

    @property
    def model(self) -> str:
        return self._model

    def suggest(self, names: Sequence[str]) -> list[tuple[str | None, float]]:
        """timeout_s - на все партии разом: прогон ждёт подсказок не дольше него. Что не успели
        спросить, остаётся без подсказки; сбой первой же партии - исключение."""
        deadline = time.monotonic() + self._timeout
        out: list[tuple[str | None, float]] = []
        for i in range(0, len(names), self._batch):
            batch = list(names[i : i + self._batch])
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                reply = self._ask(batch, remaining)
            except TimeoutError:
                if not out:
                    raise
                break
            rows = parse_rows(reply)
            out.extend(rows.get(j, (None, 0.0)) for j in range(len(batch)))
        return out + [(None, 0.0)] * (len(names) - len(out))

    def _ask(self, batch: list[str], timeout: float) -> str:
        classes = "\n".join(f"  {c} - {t}" for c, t in CLASS_TEXT.items())
        listing = "\n".join(f"{j}. {name}" for j, name in enumerate(batch))
        prompt = (
            "Ты разбираешь имена слоёв и блоков чертежа благоустройства улицы в Москве. "
            "Для каждого имени выбери класс объекта из списка. Если смысл неясен - unknown.\n"
            f"Классы:\n{classes}\n\n{KNOWLEDGE}\n\nИмена (номер. имя):\n{listing}\n"
            "Ответь JSON: rows - по строке на каждый номер: id, cls, confidence 0..1."
        )
        payload = {
            "model": self._model,
            "messages": [{"role": "user", "content": prompt}],
            "format": SCHEMA,
            "stream": False,
            "think": False,
            "options": {"temperature": 0, "num_ctx": 8192},
        }
        request = urllib.request.Request(  # noqa: S310 - адрес задаёт администратор стенда
            f"{self._url}/api/chat",
            json.dumps(payload).encode("utf-8"),
            {"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
                return json.loads(response.read().decode("utf-8"))["message"]["content"]
        except (http.client.HTTPException, ValueError, KeyError, TypeError) as error:
            # Ломаный ответ (не-HTTP сервис на адресе, обрыв, чужой JSON) - тот же сбой
            # модели, что и отказ соединения: прогон пишет его в журнал и идёт дальше.
            message = f"Ollama {self._url}: {type(error).__name__}: {error}"
            raise OSError(message) from error
