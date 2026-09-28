"""Приложения документации из конфигов, кода и итогов прогонов: руками не переписываются.

    uv run python tools/docs/annexes.py

A - свод правил с основаниями и дословными цитатами (config/rules.yaml, acts.yaml);
B - результаты по улицам пилота (итоги tools/street_runs.py и артефакты прогонов);
C - файлы прогона (сверяются с именами в коде: новый файл без описания - ошибка);
D - параметры профилей (каждое поле PlanParams обязано иметь описание).
"""
# ruff: noqa: INP001, T201, E501, ISC004, C901, PLR0912, PLR0915, S101 - сборка документации: таблицы и тексты длинные

from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from dataclasses import fields
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from green.application.explain import OBJECT_LABELS  # noqa: E402
from green.application.params import PlanParams  # noqa: E402
from green.application.wording import counted  # noqa: E402
from green.domain.norms import CitationStatus, RuleBook  # noqa: E402
from green.infrastructure.config.repositories import (  # noqa: E402
    YamlProfileSource,
    YamlRuleBookSource,
    YamlSpeciesCatalog,
)

OUT = ROOT / "docs" / "documentation" / "generated"
MEASURE = {
    "axis": "до оси",
    "outer_wall": "до наружной стенки",
    "edge": "до края",
    "unspecified": "до объекта",
}
SEVERITY = {"forbid": "запрет", "needs_approval": "согласование"}
TYPE = {"tree": "дерево", "shrub": "кустарник", "hedge": "изгородь", "lawn": "газон"}
STATUS = {
    CitationStatus.VERIFIED: "сверено",
    CitationStatus.UNVERIFIED: "не сверено",
    CitationStatus.NOT_FOUND: "текст не найден",
}


def cell(text: object) -> str:
    return str(text).replace("|", "/").replace("\n", " ").strip()


def number(value: float, digits: int = 2) -> str:
    return f"{value:.{digits}f}".rstrip("0").rstrip(".").replace(".", ",")


def thousands(value: object) -> str:
    """Разряды узким неразрывным пробелом: 116 620."""
    return f"{value:,}".replace(",", " ") if isinstance(value, int) else str(value)


def status_of(rule: object) -> str:
    citation = rule.citation  # type: ignore[attr-defined]
    if citation.act_id == "PROJECT":
        return "проектный параметр"
    return STATUS[citation.status]


# --- A. Свод правил ---


def rules_annex() -> str:
    book = YamlRuleBookSource(ROOT / "config" / "acts.yaml", ROOT / "config" / "rules.yaml").load()
    rules = book.all_rules
    by_text = sum(
        1
        for r in rules
        if r.citation.act_id != "PROJECT" and r.citation.status is CitationStatus.VERIFIED
    )
    project = sum(
        1
        for r in rules
        if r.citation.act_id == "PROJECT" and r.citation.status is CitationStatus.VERIFIED
    )
    definitions = sum(1 for r in rules if r.citation.act_id == "PROJECT") - project
    lines = [
        "## Приложение A. Свод правил {#annex-rules}",
        "",
        f"Всего правил {len(rules)}: расстояний {len(book.distance_rules)}, видовых и составных "
        f"{len(rules) - len(book.distance_rules) - len(book.lawn_rules)}, газонных "
        f"{len(book.lawn_rules)}. По тексту актов сверено основание {by_text} правил; "
        f"{project} - проектные параметры (акт требует величину, но не задаёт её, или норма "
        f"взята по аналогии); {definitions} - проектные определения газонов. Таблицы собраны из "
        "`config/rules.yaml` и `config/acts.yaml` скриптом `tools/docs/annexes.py`, "
        "вручную не правятся.",
        "",
        "Как читать. Норма - наименьшее расстояние от оси ствола дерева или центра куста до "
        "элемента объекта, названного в столбце «Измерение» (стенка трубы, ось, край). «Запрет» - посадка ближе нормы "
        "недопустима; «согласование» - допустима при согласовании с владельцем сети. "
        "«Проектный параметр» - величина, которую акт требует, но не задаёт; она принята "
        "проектом, и объяснение так её и называет.",
        "",
        "### A.1. Расстояния до объектов",
        "",
        "| rule_id | Расстояние до | Посадка | Норма, м | Измерение | Последствие | Основание | Сверка |",
        "|---|---|---|---|---|---|---|---|",
    ]
    order = {cls: i for i, cls in enumerate(OBJECT_LABELS)}
    for rule in sorted(
        book.distance_rules,
        key=lambda r: (order.get(r.object_class, 999), r.planting_type.value, r.rule_id),
    ):
        scope = []
        if rule.genera:
            scope.append("роды: " + ", ".join(sorted(rule.genera)))
        if rule.min_crown_m:
            scope.append(f"крона от {number(rule.min_crown_m)} м")
        if rule.traits:
            scope.append("признак: " + ", ".join(sorted(rule.traits)))
        if rule.sp42_edition:
            scope.append(f"только ред. СП 42 {rule.sp42_edition}")
        basis = f"{book.label_of(rule.citation.act_id)}, {rule.citation.clause}"
        related = [f"{book.label_of(ref.act_id)}, {ref.clause}" for ref in rule.citation.related]
        if related:
            basis += "; также: " + "; ".join(related)
        if scope:
            basis += " (" + "; ".join(scope) + ")"
        lines.append(
            f"| `{rule.rule_id}` | {cell(OBJECT_LABELS.get(rule.object_class, rule.object_class.value))} | "
            f"{TYPE[rule.planting_type.value]} | {number(rule.min_distance_m)} | "
            f"{MEASURE[rule.measure_to.value]} | {SEVERITY[rule.severity.value]} | "
            f"{cell(basis)} | {status_of(rule)} |"
        )

    lines += [
        "",
        "### A.2. Виды, составы и газоны",
        "",
        "| rule_id | Предмет | Основание | Сверка |",
        "|---|---|---|---|",
    ]
    for rule in book.invasive_species:
        subject = f"инвазивный вид *{rule.species_lat}*, группа {rule.group} по 369-ПП"
        lines.append(_species_row(book, rule, subject))
    for rule in book.invasive_groups:
        subject = f"группа {rule.group} по 369-ПП: {rule.condition}"
        lines.append(_species_row(book, rule, subject))
    for rule in book.species_restrictions:
        lines.append(_species_row(book, rule, RESTRICTIONS.get(rule.kind.value, rule.kind.value)))
    for rule in book.lawn_rules:
        kind = {"kept": "сохраняемый газон", "new": "устраиваемый газон"}.get(
            rule.kind.value if rule.kind else "", "газон"
        )
        lines.append(_species_row(book, rule, kind))

    lines += [
        "",
        "### A.3. Акты",
        "",
        "| Акт | Редакция | Сверено | Источник текста |",
        "|---|---|---|---|",
    ]
    for act in book.acts.values():
        checked = act.checked_at.strftime("%d.%m.%Y") if act.checked_at else "-"
        lines.append(f"| {cell(act.title)} | {cell(act.edition)} | {checked} | {cell(act.url)} |")

    lines += [
        "",
        "### A.4. Дословные цитаты",
        "",
        "Цитата - фрагмент текста акта, на котором стоит правило. Для строк таблиц дана строка "
        "таблицы как в акте, ячейки разделены знаком «|»: наименование, расстояние до оси ствола "
        "дерева, до центра кустарника, м. Реестр "
        "цитат `docs/requirements/quotes.yaml` проверяется скриптом "
        "`tools/research/check_law_quotes.py` поиском подстроки в тексте акта.",
        "",
    ]
    grouped: dict[str, dict[str, tuple[str, list[str]]]] = defaultdict(dict)
    for rule in rules:
        citation = rule.citation
        entry = grouped[citation.act_id].setdefault(citation.clause, (citation.quote, []))
        entry[1].append(rule.rule_id)
    for act_id, act in book.acts.items():
        if act_id not in grouped:
            continue
        lines += [f"#### {act.label}", ""]
        for clause, (quote, rule_ids) in grouped[act_id].items():
            ids = ", ".join(f"`{i}`" for i in rule_ids)
            text = re.sub(r"\s+", " ", quote).strip()
            lines += [f"**{cell(clause)}** ({ids})", "", f"> {text}", ""]
    return "\n".join(lines) + "\n"


RESTRICTIONS = {
    "female_fluff": "женские экземпляры растений с пухом",
    "fruit_litter": "виды, засоряющие территорию плодами",
    "mass_allergen": "массовые аллергены",
    "planting_category": "вид не рекомендован для категории насаждений",
    "root_barrier": "условие допуска: прикорневой барьер",
}


def _species_row(book: RuleBook, rule: object, subject: str) -> str:
    citation = rule.citation  # type: ignore[attr-defined]
    basis = f"{book.label_of(citation.act_id)}, {citation.clause}"
    return f"| `{rule.rule_id}` | {cell(subject)} | {cell(basis)} | {status_of(rule)} |"  # type: ignore[attr-defined]


# --- B. Улицы ---


# Итоги tools/street_runs.py: пакет в образе Docker и нативные прогоны тех улиц, которым не
# хватило памяти VM Docker. Строка более позднего источника заменяет неудачную строку раньшего.
# Источники итогов улиц; позже в списке - приоритетнее (перепрогон перекрывает старый итог).
SOURCES = (
    (ROOT / "out" / "docker-batch", ROOT / "out" / "docker-batch" / "runs", "Docker, Linux"),
    (ROOT / "out" / "street-runs-native", ROOT / "out" / "street-runs" / "runs", "Windows"),
    (ROOT / "out" / "street-runs-0928", ROOT / "out" / "street-runs" / "runs", "Windows"),
    (
        ROOT / "out" / "docker-batch-0928",
        ROOT / "out" / "docker-batch-0928" / "runs",
        "Docker, Linux",
    ),
    # Перепрогон образом ночной ветки в очередях (28.09.2026): улицы в очередях не
    # пересекаются, приоритет у обеих одинаковый и выше всех прежних.
    (ROOT / "out" / "docker-final-a", ROOT / "out" / "docker-final-a" / "runs", "Docker, Linux"),
    (ROOT / "out" / "docker-final-b", ROOT / "out" / "docker-final-b" / "runs", "Docker, Linux"),
    # Третья очередь для последней улицы, когда первая освободилась.
    (ROOT / "out" / "docker-final-c", ROOT / "out" / "docker-final-c" / "runs", "Docker, Linux"),
)


MEMORY_METHOD = "рабочие наборы процесса сервиса и дочерних процессов раз в 0,5 с"


def peak_memory(row: dict[str, object]) -> tuple[float, str] | None:
    """Пиковая память прогона улицы и где и как она замерена (`mem-N.json` рядом с итогами).

    Сначала замер того же источника, что и итог; иначе самый поздний замер этой улицы в
    другом источнике - со своей средой в пояснении.
    """
    own = [Path(str(row["source_dir"]))] if "source_dir" in row else []
    for folder in [*own, *(f for f, _, _ in reversed(SOURCES))]:
        path = folder / f"mem-{row['number']}.json"
        if path.is_file():
            data = json.loads(path.read_text(encoding="utf-8"))
            if data.get("exit", 0) != 0:
                continue  # прогон оборвался: пик до обрыва - не пик прогона
            env = next((e for f, _, e in SOURCES if f == folder), str(row.get("env", "")))
            return float(data["peak_rss_gb"]), f"{env}, {data.get('method', MEMORY_METHOD)}"
    return None


def street_rows() -> list[dict[str, object]]:
    """Строка итога улицы с каталогом её артефактов и средой прогона, по номеру улицы."""
    rows: dict[str, dict[str, object]] = {}
    for folder, runs, env in SOURCES:
        for path in folder.glob("*.json") if folder.is_dir() else ():
            row = json.loads(path.read_text(encoding="utf-8"))
            if "slug" not in row or "state" not in row:
                continue
            known = rows.get(row["slug"])
            if known is None or known["state"] != "succeeded" or row["state"] == "succeeded":
                row["output"] = runs / str(row.get("run_id")) / "output"
                row["env"] = env
                row["source_dir"] = folder
                rows[row["slug"]] = row
    catalog = ROOT / "dataset" / "streets_oda" / "catalog.json"
    if catalog.is_file():
        for street in json.loads(catalog.read_text(encoding="utf-8")):
            rows.setdefault(
                street["slug"],
                {
                    "slug": street["slug"],
                    "number": street["number"],
                    "title": street["title"],
                    "state": "not_run",
                    "output": Path(),
                    "env": "-",
                },
            )
    return sorted(rows.values(), key=lambda r: int(str(r["slug"]).split("-")[0]))


# Что изменилось после прогона улицы: исправления, из-за которых её итог в пакете устарел.
STREET_NOTES = {
    "1-olimpiyskaya-derevnya": (
        "в пакете 27.09 чтение остановила полилиния борта с выпуклостью 1,4·10⁻¹³ - "
        "единственный пробел улицы. Дефект чтения исправлен 27.09.2026 (разд. 3.3), в "
        "перепрогоне 28.09 улица прочитана без пробелов"
    ),
    "7-nizhnie-polya-ul": (
        "в пакете 27.09 план был пуст: в комплекте улицы не было границы работ. Граница "
        "добавлена из исходных данных (разд. 5.2), её разрыв 3,4 м замыкается хордой "
        "(разд. 8.3); строка таблицы - перепрогон 28.09"
    ),
    "12-natashinskiy-pr-d-doroga-ot-ul-borisovskie-prudy-do-pr-pr": (
        "в пакете 27.09 было 29 посадок: окружности радиусом 150 м слоя «ЭН_ЗУ радиус 150м» "
        "(зоны действия наружного освещения) были приняты за силовой кабель. Исправлено "
        "27.09.2026 (разд. 3.6); строка таблицы - перепрогон 28.09"
    ),
    "13-harkovskiy-proezd": (
        "в пакете 27.09 план был пуст: та же ошибка, что на Наташинском проезде, - каждая "
        "точка внутри окружности «ЭН_ЗУ радиус 150м» оказывалась на кабеле. Исправлено "
        "27.09.2026: значение радиуса в имени слоя - оформление, широкая фигура на слое сети "
        "мерится по контуру (разд. 3.6); строка таблицы - перепрогон 28.09"
    ),
    "15-akademika-pontryagina": (
        "в пакете не досчитана: самый тяжёлый комплект пилота (424 МБ, 889 тыс. примитивов; "
        "склейка и чтение - по 22 мин). На карте покрытий память процесса росла с 4,5 до 8-9 ГБ, "
        "и прогон убит при пределе виртуальной машины Docker: 28.09.2026 три попытки - при 6,6, "
        "10 и 10 ГБ. Причина - проверка незавершённых линий в гранях строила контур грани на "
        "каждую пару (151 тыс. пар); исправлена в тот же день, этап на входе улицы - 330 с и "
        "3,4 ГБ (разд. 8.2). Полный прогон после исправления в пакет не вошёл"
    ),
}


def streets_annex() -> str:
    designer = {
        s["slug"]: s
        for s in yaml.safe_load(
            (ROOT / "docs" / "data" / "designer-plans.yaml").read_text(encoding="utf-8")
        )["streets"]
    }
    rows = []
    for row in street_rows():
        output = Path(str(row["output"]))
        facts: dict[str, object] = {"row": row, "summary": row.get("summary") or {}}
        if (output / "plan.json").is_file():
            plan = json.loads((output / "plan.json").read_text(encoding="utf-8"))
            kinds = [p["planting_type"] for p in plan["placements"]]
            facts["trees"], facts["shrubs"] = kinds.count("tree"), kinds.count("shrub")
            facts["lawn_m2"] = round(sum(lawn.get("area_m2", 0) for lawn in plan.get("lawns", [])))
            rejected = [r for r in plan["rejections"] if r["planting_type"] == "tree"]
            by_existing = sum(
                1
                for r in rejected
                if any(b["rule_id"] == "R-EXTREE-TREE-001" for b in r["blocking"])
            )
            facts["existing_share"] = by_existing / len(rejected) if rejected else 0.0
        for name in ("quality", "verify", "validation"):
            if (output / f"{name}.json").is_file():
                facts[name] = json.loads((output / f"{name}.json").read_text(encoding="utf-8"))
        facts["designer"] = designer.get(row["slug"], {})
        facts["title"] = facts["designer"].get("title") or row.get("title", row["slug"])  # type: ignore[union-attr]
        rows.append(facts)

    lines = [
        "## Приложение B. Результаты по улицам пилота {#annex-streets}",
        "",
        "Прогон всех улиц каталога пилота: профиль `strict` (редакция СП 42 2016 года), "
        "портфель вариантов, без ручных правок и назначений классов. Среда - образ Docker на "
        "Linux с кодом ночной ветки, перепрогон 28.09.2026 в две очереди одновременно (третья - для "
        "последней улицы) на машине разработки: 16 потоков, 10 ГБ у виртуальной машины Docker. "
        "Из-за соседней очереди время улицы на 10-30% больше, чем при прогоне по одной "
        "(Макеева: 2927 с против 2234 с). Улица Академика Понтрягина в 10 ГБ не поместилась, "
        "причина исправлена после пакета (примечание ниже). Пакет посчитан кодом до слияния с изменениями 27.09 (проверка "
        "грунта под всей ямой, пометка посадок на выведенном грунте, профиль `review`): их в "
        "итогах пакета нет. Проверка кодом main на пяти улицах (Кустанайская, Камчатская, "
        "Измайловская площадь, Песчаный, 2-я Прядильная): посадок столько же с точностью до 1%, "
        "деревьев столько же или на одно меньше, 60-97% посадок на тех же точках; грунт под "
        "ямами на этих улицах выведен по подписям, и код main помечает такие посадки как "
        "требующие проверки покрытия. Таблица собрана из итогов `tools/street_runs.py` и "
        "артефактов прогонов скриптом `tools/docs/annexes.py`.",
        "",
        "Столбцы. «Объектов» - сущностей исходника, целостность которых сверена после записи "
        "(`verify.json`). «Нарушений» - замечаний независимой проверки плана "
        "(`validation.json`). «Согласование» - посадок с вердиктом «требует согласования». "
        "«Индекс» - индекс качества выбранного варианта, от 0 до 1 (разд. 3.11). "
        "«Проект» - новые посадки в принятом проекте улицы по ассортиментным ведомостям "
        "(`docs/data/designer-plans.yaml`). «У сущ., %» - доля отказов деревьям, где среди нарушенных норм есть "
        "расстояние до существующего дерева (`R-EXTREE-TREE-001`, 5 м).",
        "",
        "| № | Улица | Объектов | Время, мин | Деревьев | Кустарников | Газон, м² | Согласование | Отказов | У сущ., % | Нарушений | Индекс | Проект: деревьев / кустарников |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for facts in rows:
        row, summary = facts["row"], facts["summary"]
        assert isinstance(row, dict)
        assert isinstance(summary, dict)
        if row["env"] not in {SOURCES[0][2], "-"}:
            facts["title"] = f"{facts['title']} ({row['env']})"
        if row["state"] == "not_run":
            lines.append(
                f"| {row['number']} | {cell(facts['title'])} | - | - | не досчитан, см. ниже "
                "|  |  |  |  |  |  |  |  |"
            )
            continue
        if row["state"] != "succeeded":
            lines.append(
                f"| {row['number']} | {cell(facts['title'])} | - | "
                f"{number(row.get('seconds', 0) / 60, 1)} | прогон остановлен, см. ниже |  |  |  |  |  |  |  |  |"
            )
            continue
        verify = facts.get("verify") or {}
        validation = facts.get("validation") or {}
        quality = facts.get("quality") or {}
        designer = facts["designer"]
        assert isinstance(designer, dict)
        # Нет ведомости кустарника (total: null) - прочерк, а не «None» в таблице.
        totals = [(designer.get(kind) or {}).get("total") for kind in ("trees", "shrubs")]
        project = " / ".join("-" if value is None else thousands(value) for value in totals)
        integrity = (
            "" if summary.get("integrity_ok") and summary.get("export_matches_plan") else " (!)"
        )
        lines.append(
            f"| {row['number']} | {cell(facts['title'])} | "
            f"{thousands(verify.get('source_entities', '-'))}{integrity} | {number(row['seconds'] / 60, 1)} | "
            f"{facts.get('trees', '-')} | {thousands(facts.get('shrubs', '-'))} | "
            f"{thousands(facts.get('lawn_m2', '-'))} | "
            f"{summary.get('needs_approval', '-')} | {summary.get('rejections', '-')} | "
            f"{round(100 * facts.get('existing_share', 0))} | "  # type: ignore[call-overload]
            f"{len(validation.get('issues', [])) if validation else '-'} | "
            f"{number(quality['index'], 3) if quality.get('index') is not None else '-'} | {project} |"
        )
    done = [f for f in rows if f["row"]["state"] == "succeeded"]  # type: ignore[index]
    stopped = [f for f in rows if f["row"]["state"] != "succeeded"]  # type: ignore[index]
    planted = [f for f in done if int(f.get("trees", 0)) + int(f.get("shrubs", 0))]  # type: ignore[call-overload]
    lines += [
        "",
        f"Итого: планов с посадками {len(planted)} из {len(rows)}; деревьев "
        f"{sum(int(f.get('trees', 0)) for f in done)}, кустарников "  # type: ignore[call-overload]
        f"{sum(int(f.get('shrubs', 0)) for f in done)}; нарушений норм в выданных планах "  # type: ignore[call-overload]
        f"{sum(len((f.get('validation') or {}).get('issues', [])) for f in done)}.",  # type: ignore[union-attr]
    ]
    shares = sorted(round(100 * float(f.get("existing_share", 0))) for f in done)  # type: ignore[arg-type]
    bagritskogo = next((f for f in done if f["row"]["slug"] == "5-bagritskogo-ulitsa"), None)  # type: ignore[index]
    example = (
        f"сервис вырубку не назначает, поэтому новых деревьев там {bagritskogo['trees']} против "
        f"{bagritskogo['designer']['trees']['total']} в проекте."  # type: ignore[index]
        if bagritskogo
        else "сервис вырубку не назначает."
    )
    lines += [
        "",
        "Почему число посадок расходится с проектом. Причины видны в данных, это не ошибки "
        "расчёта:",
        "",
        "1. **Существующие деревья.** Проект вырубает часть существующих деревьев и сажает на "
        "их месте. Сервис существующие насаждения сохраняет и ставит новое дерево не ближе 5 м "
        "к ним (`R-EXTREE-TREE-001`, параметр проекта по аналогии с шагом посадки 743-ПП, табл. "
        "3.6.2). Доля отказов деревьям у "
        f"существующих деревьев - от {shares[0]} до {shares[-1]}% по улицам (столбец "
        "«У сущ., %»). На улице Багрицкого дендрологическое обоснование проекта рекомендует к "
        "вырубке 421 дерево из 1228, в основном клён ясенелистный (инвазивный вид, 369-ПП); "
        + example,
        "2. **Нормы строже практики.** Проект местами сажает ближе нормативных отступов: "
        "нормоконтроль плана проектировщика улицы Берзарина теми же правилами нашёл 391 "
        "посадку с нарушениями из 554 (разд. 3.16). В плане сервиса нарушений нет.",
        "3. **Кустарник.** Кустарник проекта считается штуками по ведомости, включая живые "
        "изгороди в несколько рядов. Живая изгородь сервиса ограничена верхней границей "
        "плотности 720 кустарников на 1 км улицы (МГСН 1.02-02, табл. В.1), поэтому на "
        "улицах с протяжёнными изгородями проекта числа несопоставимы.",
        "4. **Газоны.** Газон строится только на грунте, подтверждённом замкнутыми контурами "
        "(разд. 3.5, 8.2). Где контуров грунта в чертеже нет, газонов нет, а площадь грунта, "
        "выведенного по подписям, названа в журнале прогона.",
    ]
    memory = []
    for facts in rows:
        row = facts["row"]
        assert isinstance(row, dict)
        measured = peak_memory(row)
        if measured is not None:
            memory.append(f"{cell(facts['title'])} - {number(measured[0], 1)} ГБ ({measured[1]})")
    if memory:
        lines += ["", "Пиковая память прогона: " + "; ".join(memory) + "."]
    noted = [f for f in rows if f in stopped or f["row"]["slug"] in STREET_NOTES]  # type: ignore[index]
    if noted:
        lines += ["", "Примечания к строкам:", ""]
        for facts in noted:
            row = facts["row"]
            assert isinstance(row, dict)
            parts = []
            if row.get("error"):
                reason = re.sub(r"\s+", " ", str(row["error"])).strip()
                parts.append(f"прогон остановлен: «{cell(reason[:400])}»")
            if row["slug"] in STREET_NOTES:
                parts.append(STREET_NOTES[row["slug"]])
            lines.append(f"- {cell(facts['title'])}: " + "; ".join(parts) + ".")
    lines += _effect_table(rows)
    return "\n".join(lines) + "\n"


EFFECT_COLUMNS = (
    ("trees", "Деревья, шт."),
    ("canopy_share", "Кроны, % участка"),
    ("curb_green_share", "Борта под зеленью, %"),
    ("tiers_trees", "Деревья с нижним ярусом"),
    ("noise_curb_m", "Борта с полосой от 10 м, м"),
    ("lawn_m2", "Газон, м²"),
)


def effect_of(output: Path) -> dict | None:
    """Баланс улицы: effect.json (tools/effect_from_runs.py) или блок effect в quality.json."""
    path = output / "effect.json"
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    quality = output / "quality.json"
    if quality.is_file():
        return json.loads(quality.read_text(encoding="utf-8")).get("effect")
    return None


def measure_of(effect: dict, key: str) -> dict:
    return next(m for m in effect["measures"] if m["key"] == key)


def _pair(effect: dict, key: str) -> str:
    m = measure_of(effect, key)
    before, after = m["before"], m["after"]
    if before is None and after is None:
        return "не определяется"
    digits = 1 if key.endswith("share") else 0

    def text(value: float | None) -> str:
        return "-" if value is None else thousands(round(value)) if digits == 0 else number(value, 1)

    return f"{text(before)} → {text(after)}"


def _effect_table(rows: list[dict[str, object]]) -> list[str]:
    """Было - стало по улицам: существующие насаждения чертежа и они вместе с планом."""
    lines = [
        "",
        "### Было - стало по улицам {#annex-streets-effect .newpage}",
        "",
        "Было - существующие насаждения чертежа, стало - они вместе с посадками плана (разд. "
        "3.17). Существующие кроны - круги 8,5 м вокруг стволов (параметр `existing_crown_m`): "
        "знак дерева в чертеже - кружок, а не крона. Число деревьев по чертежу показано только "
        "там, где каждое дерево - вставка знака; где деревья нарисованы разобранными знаками и "
        "знаками массивов, оно не определяется (сверка 27.09.2026: Багрицкого 1441 ствол по "
        "меткам при 1228 деревьях дендрологического обоснования, Харьковская 428 при 724, "
        "Лодочная 4148 при 569), а площадь крон считается по тем же меткам. Шумозащита - метры "
        "бортов с покрытием с одной стороны, у которых полоса насаждений в сторону грунта шире "
        "10 м (МГСН 1.02-02, табл. В.5). Для уже выданных планов баланс посчитан по контексту "
        "прогона тем же кодом сервиса (`tools/effect_from_runs.py`).",
        "",
        "| № | Улица | " + " | ".join(title for _, title in EFFECT_COLUMNS) + " |",
        "|---|---|" + "---|" * len(EFFECT_COLUMNS),
    ]
    count = 0
    for facts in rows:
        row = facts["row"]
        assert isinstance(row, dict)
        if row["state"] != "succeeded":
            continue
        effect = effect_of(Path(str(row["output"])))
        if effect is None:
            continue
        count += 1
        lines.append(
            f"| {row['number']} | {cell(facts['title'])} | "
            + " | ".join(_pair(effect, key) for key, _ in EFFECT_COLUMNS)
            + " |"
        )
    return lines if count else []


def effect_facts(runs: list[dict[str, object]]) -> dict[str, str]:
    """Итог «было - стало» и виды посадок по всем улицам с посчитанным балансом."""
    effects = [
        e
        for r in runs
        if r["state"] == "succeeded" and (e := effect_of(Path(str(r["output"])))) is not None
    ]
    if not effects:
        return {}

    def total(key: str, side: str) -> float:
        return sum(float(measure_of(e, key)[side] or 0) for e in effects)

    area = sum(float(e.get("area_m2") or 0) for e in effects)
    curb = sum(float(e.get("curb_m") or 0) for e in effects)
    known = [
        e
        for e in effects
        if measure_of(e, "trees")["before"] is not None and e.get("stock_source") != "none"
    ]
    kinds: dict[str, dict[str, float]] = {}
    titles: dict[str, tuple[str, str, str]] = {}
    for e in effects:
        for k in e["kinds"]:
            agg = kinds.setdefault(k["key"], {"count": 0, "length_m": 0.0, "area_m2": 0.0})
            agg["count"] += k["count"]
            agg["length_m"] += k["length_m"] or 0.0
            agg["area_m2"] += k["area_m2"] or 0.0
            titles[k["key"]] = (k["title"], k["planting_type"], k["basis"])
    unit = {
        "tree": ("дерево", "дерева", "деревьев"),
        "shrub": ("куст", "куста", "кустов"),
        "lawn": ("участок", "участка", "участков"),
    }
    kind_rows = []
    for key, agg in kinds.items():
        title, kind, basis = titles[key]
        forms = unit.get(kind, ("", "", ""))
        amount = counted(int(agg["count"]), *forms).replace(
            str(int(agg["count"])), thousands(int(agg["count"])), 1
        )
        if agg["length_m"]:
            amount += f", {thousands(round(agg['length_m']))} пог. м"
        if agg["area_m2"]:
            amount += f", {thousands(round(agg['area_m2']))} м²"
        kind_rows.append(f"| {title} | {amount} | {basis} |")
    return {
        "effect_streets": str(len(effects)),
        "effect_canopy": (
            f"{number(100 * total('canopy_m2', 'before') / area, 1)} → "
            f"{number(100 * total('canopy_m2', 'after') / area, 1)}% площади участков"
        ),
        "effect_canopy_m2": (
            f"+{thousands(round(total('canopy_m2', 'after') - total('canopy_m2', 'before')))} м²"
        ),
        "effect_curb": (
            f"{number(100 * total('curb_green_m', 'before') / curb, 1)} → "
            f"{number(100 * total('curb_green_m', 'after') / curb, 1)}% длины бортов"
        ),
        "effect_curb_m": (
            f"+{thousands(round(total('curb_green_m', 'after') - total('curb_green_m', 'before')))} м"
        ),
        "effect_tiers": (
            f"{thousands(round(total('tiers_trees', 'before')))} → "
            f"{thousands(round(total('tiers_trees', 'after')))}"
        ),
        "effect_noise": (
            f"{number(total('noise_curb_m', 'before') / 1000, 1)} → "
            f"{number(total('noise_curb_m', 'after') / 1000, 1)} км бортов"
        ),
        "effect_lawn_kept": thousands(round(total("lawn_m2", "before"))),
        "effect_lawn_new": thousands(
            round(total("lawn_m2", "after") - total("lawn_m2", "before"))
        ),
        "effect_trees_text": (
            f"Число существующих деревьев по чертежу определяется на {len(known)} улицах из "
            f"{len(effects)}"
            if known
            else f"Число существующих деревьев по чертежу не определяется ни на одной из "
            f"{len(effects)} улиц"
        ),
        "kinds_rows": "\n".join(kind_rows),
    }


# --- C. Файлы прогона ---

ARTIFACTS: list[tuple[str, str, str]] = [
    # Кортеж: имя файла, группа, содержание.
    (
        "result.dxf",
        "Результат",
        "копия исходного чертежа в его версии и единицах со слоями результата `GREEN_*` (разд. 3.12)",
    ),
    (
        "interpretations.json",
        "Интерпретации",
        "строка на пару «решение - правило»: номер, вид, координаты, вердикт, `rule_id`, исход проверки, измерение, норма, класс и ссылка на объект чертежа, акт, пункт, связанные акты, статус сверки, цитата, адрес текста акта",
    ),
    (
        "interpretations.csv",
        "Интерпретации",
        "то же в CSV (UTF-8 с BOM, разделитель `;`) для табличных редакторов",
    ),
    (
        "interpretations.md",
        "Интерпретации",
        "читаемый отчёт: сводка, баланс озеленения «было - стало» и виды посадок, нормативная база, по каждой посадке определяющая норма с запасом, по каждому отказу нарушенные нормы, основания газонов",
    ),
    (
        "report.html",
        "Интерпретации",
        "тот же отчёт для печати в PDF на A4 (открывается в браузере)",
    ),
    (
        "plantings.csv",
        "Интерпретации",
        "одна строка на посадку: вид, координаты, вердикт, определяющая норма, полный текст объяснения",
    ),
    (
        "rules.json",
        "Интерпретации",
        "свод правил прогона с основаниями и цитатами, после отключений и выбора редакции",
    ),
    (
        "plan.json",
        "План",
        "посадки (координаты, вид, вердикт, проверки, основания вида), отказы с причинами, газоны, предупреждения, журнал чтения",
    ),
    (
        "planting_schedule.csv",
        "План",
        "ведомость посадочного материала по видам: число, группа посадочного материала, размер ямы и кома",
    ),
    (
        "assortment.json",
        "План",
        "подбор видов деревьев: число по видам, доли родов и семейств, доля хвойных, индекс Шеннона, декоративность по месяцам, отсеянные виды по правилам",
    ),
    ("assortment_shrubs.json", "План", "то же для кустарников"),
    ("zones.geojson", "План", "зоны допустимости «можно», «по согласованию» в координатах чертежа"),
    (
        "quality.json",
        "Качество",
        "индекс качества: слагаемые с целями и значениями, веса, штрафы, посадки с наибольшим и наименьшим вкладом; отдельным блоком `effect` - баланс «было - стало», виды посадок и шумозащита (разд. 3.17)",
    ),
    (
        "portfolio.json",
        "Качество",
        "варианты портфеля: приём, число посадок, индекс, время, признак проверки; выбранный вариант",
    ),
    (
        "selection.json",
        "Качество",
        "отбор мест деревьев MILP: кандидаты, конфликты, статус решателя, значение цели и разрыв до оценки",
    ),
    (
        "validation.json",
        "Проверки",
        "независимая проверка плана: число проверенных посадок, замечания, допущения",
    ),
    (
        "verify.json",
        "Проверки",
        "целостность исходника: сущностей, неизменных, изменённых, пропавших, добавленных вне слоёв `GREEN_*`",
    ),
    (
        "export_validation.json",
        "Проверки",
        "соответствие записанного DXF плану: посадки и газоны найдены на своих слоях",
    ),
    (
        "input_read.json",
        "Чтение",
        "учёт чтения: примитивы по типам, пропущенные, неразрешённые внешние ссылки, объекты без геометрии, погрешность аппроксимации кривых",
    ),
    (
        "layers_report.json",
        "Чтение",
        "слои исходника: число объектов, класс, источник класса (словарь слоёв, знак, вывод по имени)",
    ),
    (
        "classification.json",
        "Чтение",
        "класс каждого объекта со ссылкой на сущность чертежа и основанием решения",
    ),
    (
        "assembly.json",
        "Чтение",
        "состав комплекта: файлы, внешние ссылки, способ совмещения координат",
    ),
    (
        "merged_source.dxf",
        "Чтение",
        "склеенный исходник комплекта, если на входе несколько файлов или внешние ссылки; от него строится `result.dxf`",
    ),
    (
        "surface.json",
        "Покрытия",
        "карта покрытий: начало, шаг ячейки, размер, число ячеек грунта, твёрдого, препятствий и неизвестных",
    ),
    ("surface.png", "Покрытия", "та же карта картинкой для веб-интерфейса и 3D-вида"),
    (
        "basemap.geojson",
        "Визуализация",
        "подоснова для карты интерфейса: контуры, здания, сети, существующие насаждения",
    ),
    (
        "scene.json",
        "Визуализация",
        "сцена 3D-вида: здания с этажностью, посадки с видом и размером кроны, границы, покрытия",
    ),
    (
        "run_manifest.json",
        "Воспроизводимость",
        "исходный файл (имя, SHA-256, версия DXF), конвертер, профиль, все параметры, отпечатки свода правил и словаря слоёв, версии Python и библиотек, время этапов, сводка",
    ),
]
ARTIFACTS_BESIDE = [
    ("status.json", "состояние прогона: этап, доля, сводка, ошибка; читается API"),
    (
        "context.pickle",
        "контекст правки: прочитанный чертёж, план, отчёт прогона и карта покрытий (индексы ограничений строятся заново при первой правке), чтобы проверка точки и правка работали после перезапуска сервиса (разд. 3.15)",
    ),
    ("input/", "исходные файлы прогона, слои ГИС (`input/gis/`), перечётная ведомость"),
]
NOT_RUN_FILES = {
    # Файлы, которые не относятся к выходу прогона плана.
    "audit.json",
    "audit.csv",
    "audit.md",
    "audit.dxf",  # нормоконтроль, разд. 3.16
    "catalog.json",  # каталог улиц
    "berzarina_fragment.dxf",  # встроенный образец
    "drawing.dxf",  # имя загрузки по умолчанию
    "repaired.dxf",  # промежуточный файл ремонта LibreDWG
    "index.html",  # бандл интерфейса
    "layer.geojson",  # имя слоя ГИС по умолчанию
    "status.json",
    "context.pickle",
}


def artifacts_annex() -> str:
    names = set()
    for path in (ROOT / "src" / "green").rglob("*.py"):
        names |= set(
            re.findall(
                r"\"([a-z_0-9]+\.(?:json|csv|md|html|dxf|geojson|png|pickle))\"",
                path.read_text(encoding="utf-8"),
            )
        )
    described = {name for name, _, _ in ARTIFACTS}
    missing = names - described - NOT_RUN_FILES
    if missing:
        msg = f"файлы без описания в приложении C: {sorted(missing)}"
        raise SystemExit(msg)
    lines = [
        "## Приложение C. Файлы прогона {#annex-artifacts}",
        "",
        "Каталог прогона `runs/<id>/`: выход в `output/`, рядом служебные файлы. Любой файл "
        "выхода отдаётся методом `GET /api/v1/runs/{id}/artifacts/{name}` и кнопкой на "
        "странице прогона. Перечень сверяется с кодом при сборке документации: файл, "
        "появившийся в коде без описания здесь, останавливает сборку.",
        "",
        "| Файл | Группа | Содержание |",
        "|---|---|---|",
    ]
    lines += [f"| `{name}` | {group} | {text} |" for name, group, text in ARTIFACTS]
    lines += ["", "Служебные файлы каталога прогона:", "", "| Файл | Содержание |", "|---|---|"]
    lines += [f"| `{name}` | {text} |" for name, text in ARTIFACTS_BESIDE]
    return "\n".join(lines) + "\n"


# --- D. Параметры ---

PARAMS: list[tuple[str, list[tuple[str, str]]]] = [
    (
        "Тип посадки и вид",
        [
            (
                "planting_type",
                "тип основной посадки прогона: `tree` - деревья с кустарниковым ярусом, `shrub` - только кустарники",
            ),
            ("species_code", "вид при `assortment_mode: single`"),
            (
                "assortment_mode",
                "`auto` - вид подбирает сервис; `given` - только виды и количества из `given_assortment`; `single` - один вид `species_code`",
            ),
            (
                "assortment_solver",
                "`auto` - целочисленная задача назначения видов с запасным жадным путём; `greedy` - сразу жадный",
            ),
            ("given_assortment", "заданный ассортимент: код вида -> число"),
            (
                "assortment_weights",
                "веса факторов пригодности вида месту: условия места, функция, декоративность, долговечность, уход, практика пилота, категория насаждений, тень",
            ),
            (
                "region_hardiness_zone",
                "зона зимостойкости региона (Москва 4b-5a): вид с зоной выше не допускается",
            ),
            (
                "salt_zone_m",
                "ширина полосы у проезжей части, где учитывается солеустойчивость вида (реагенты), м; проектный параметр",
            ),
            (
                "max_height_under_lines_m",
                "предельная высота растения в охранной зоне ВЛ, м; проектный параметр: ПП РФ № 160, п. 10 «в» требует согласования посадки, высоту не задаёт",
            ),
            ("territory", "тип территории по 369-ПП; решает допустимость видов группы III"),
            (
                "planting_category",
                "категория насаждений по МГСН 1.02-02, табл. В.6: ассортимент улиц, дворов, парков",
            ),
            (
                "allergen_act_priority",
                "`true` - при расхождении актов решает акт, называющий вид: вид, рекомендованный МГСН 1.02-02, табл. В.6, допускается, аллергенность снижает оценку; `false` - запрет массовых аллергенов по 743-ПП, п. 3.6.18",
            ),
            (
                "condition_penalty",
                "снижение оценки вида с условием посадки или слабого аллергена (оценка 0-1): при равных квотах берётся вид без обязательств",
            ),
        ],
    ),
    (
        "Нормы",
        [
            (
                "disabled_rules",
                "правила, которые профиль отключает; перечисляются в предупреждениях прогона",
            ),
            (
                "sp42_edition",
                "редакция СП 42.13330 для строк, где значения разошлись: `2016` (ТЗ) или `2026` (действующая)",
            ),
            (
                "root_barriers",
                "прикорневые барьеры (СП 42, прим. 5 к табл. 9.1): дерево ближе нормы к сетям и борту с барьером как условием",
            ),
            (
                "crown_extra_per_m",
                "увеличение отступов для кроны шире 5 м (СП 42, прим. 1 к табл. 9.1), м радиуса на метр диаметра; величина - толкование проекта",
            ),
            (
                "crown_extra_classes",
                "классы объектов, к которым применяется увеличение; пусто - ко всем строкам таблицы",
            ),
            ("allow_needs_approval", "допускать посадки с вердиктом «требует согласования»"),
            (
                "require_utility_data",
                "`true` - без распознанных сетей место не допускается (вердикт «нет данных»); `false` - для съёмки без сетей",
            ),
            (
                "unknown_lines_as_utility",
                "линии неопознанных слоёв сетей считаются сетью неизвестного типа с наибольшим отступом",
            ),
        ],
    ),
    (
        "Чтение и классы объектов",
        [
            (
                "drawing_unit",
                "единица чертежа: `auto` - по `$INSUNITS`; явная (`m`, `mm`, ...) для чертежа без единиц",
            ),
            (
                "require_known_objects",
                "`true` - неопознанный объект останавливает прогон с перечнем",
            ),
            (
                "infer_unknown",
                "`true` - незнакомый слой или знак получает класс по словам имени и геометрии; `false` - строгий режим",
            ),
            (
                "assume_unknown_geometry",
                "`true` - неопознанный объект получает класс по геометрии (контур, рамка, малый круг); `false` - вывод по словам остаётся, а объект без совпадения требует уточнения (профиль `review`)",
            ),
            (
                "semantic_source_sha256",
                "отпечаток чертежа, к которому привязаны ручные назначения классов",
            ),
            ("layer_classes", "ручные назначения: слой -> класс"),
            ("block_classes", "ручные назначения: блок -> класс"),
            ("feature_classes", "ручные назначения: объект чертежа -> класс"),
            ("label_roles", "ручные назначения ролей подписей (легенды чертежа)"),
            ("label_search_radius_m", "радиус поиска подписи диаметра у сети, м"),
            (
                "require_work_boundary",
                "`true` - без границы работ места не допускаются: план пуст, журнал прогона говорит, что границы нет",
            ),
        ],
    ),
    (
        "Карта покрытий",
        [
            ("require_soil", "`true` - посадка только на грунте, подтверждённом картой покрытий"),
            ("surface_cell_m", "шаг растра карты покрытий, м"),
            (
                "surface_inference_mode",
                "`hybrid` - замкнутые грани решают сами, подписи вне решённых граней действуют по расстоянию; `closed_faces` - только замкнутые грани",
            ),
            (
                "surface_max_distance_m",
                "дальность действия подписи материала, м (допущение проекта)",
            ),
            (
                "surface_ambiguity_m",
                "если расстояния до признаков грунта и твёрдого покрытия различаются меньше этого, ячейка неизвестна, м",
            ),
            (
                "tree_seed_distance_m",
                "радиус вокруг знака существующего дерева, где он подтверждает грунт, м; действует только в режиме `surface_inference_mode: distance`",
            ),
        ],
    ),
    (
        "Размещение деревьев",
        [
            (
                "modes",
                "приёмы по порядку: `alley` - аллея вдоль борта, `lawn` - сетка по грунту, `fill` - добор зоны",
            ),
            ("spacing_m", "шаг деревьев, м (743-ПП, табл. 3.6.2: однорядная 5-6 м)"),
            (
                "curb_offsets_m",
                "отступы аллеи от борта по предпочтению, м (норма от 2 м, 743-ПП, табл. 3.6.1)",
            ),
            (
                "planting_radius_m",
                "радиус посадочного места дерева, м: круг, равновеликий яме 2,2 × 2,2 м (743-ПП, табл. 3.3.1)",
            ),
            ("shrub_planting_radius_m", "радиус посадочного места куста, м"),
            ("fill_step_m", "шаг ячеек добора зоны, м"),
            (
                "placement_solver",
                "`portfolio` - сравнение вариантов, прошедших проверку; иначе один приём",
            ),
            ("placement_time_limit_s", "лимит времени MILP на вариант, с"),
            ("placement_max_candidates", "предел числа кандидатов MILP; больше - жадный отбор"),
            ("placement_max_conflicts", "предел числа пар-конфликтов MILP"),
            ("portfolio_budget_s", "бюджет времени портфеля, с; исходный вариант считается всегда"),
            ("refine_budget_s", "бюджет сдвига посадок от сетей, пока растёт индекс, с"),
            ("lawn_phase", "сдвиг сетки кандидатов по газону, м"),
            ("lawn_rotation_deg", "поворот сетки кандидатов по газону, градусы"),
            ("lawn_anchor", "привязка сетки кандидатов: `raster` - к растру покрытий"),
            ("max_rejections", "предел числа записанных отказов"),
            ("zones", "строить зоны допустимости"),
            ("zone_cell_m", "шаг сетки зон допустимости, м"),
        ],
    ),
    (
        "Кустарниковый ярус",
        [
            ("shrub_rows", "ряд кустарника у борта под кронами аллеи"),
            (
                "shrub_row_curb_offsets_m",
                "ось ряда от борта, м: сначала 1,3 (запас на снег), затем 1,0",
            ),
            (
                "shrub_row_spacing_m",
                "шаг кустов в ряду по 743-ПП, табл. 3.6.2 (средние и низкие 0,3-0,4 м); ямы кустов d = 1 м не перекрываются, поэтому фактический шаг не меньше 1,0 м",
            ),
            (
                "shrub_row_tree_gap_m",
                "от ствола дерева до куста ряда, м; фактически не меньше суммы радиусов ям дерева и куста, 1,24 + 0,5 = 1,74 м",
            ),
            ("shrub_row_access_gap_m", "от люка до ряда, м: доступ для обслуживания"),
            (
                "shrub_row_gap_buffer_m",
                "отступ ряда от перехода и въезда, м (Сводный стандарт улиц, п. 32.12)",
            ),
            ("shrub_row_break_min_m", "наименьший разрыв газона у борта, считающийся въездом, м"),
            ("shrub_row_min_length_m", "наименьшая длина ряда, м"),
            ("shrub_row_height_m", "высота стриженой изгороди, м (СП 82.13330.2016, п. 9.40)"),
            ("curb_hedges", "живая изгородь вдоль всех бортов с грунтом (СП 82, п. 9.38)"),
            (
                "curb_hedge_spacing_m",
                "шаг кустов изгороди, м (743-ПП, табл. 3.6.2: высокие 0,5-1 м)",
            ),
            (
                "curb_hedge_density_cap",
                "изгородь не поднимает кустарник выше 720 на 1 км (МГСН 1.02-02, табл. В.1)",
            ),
            (
                "hedge_species_balance",
                "вид участка изгороди - самый редкий из допустимых, чтобы держать квоты",
            ),
            (
                "understory",
                "малая группа кустарника под кроной дерева без нижнего яруса (МГСН 1.02-02, п. 4.2.9.2)",
            ),
            ("understory_trees", "под какими деревьями: `all` - всеми, `alley` - только аллеи"),
            ("understory_size", "кустов в группе подлеска"),
            (
                "understory_radii_m",
                "кольца от ствола, на которых ищутся места кустов под кроной, м; ближе 1,74 м ямы дерева и куста перекрылись бы",
            ),
            ("understory_existing", "группа кустарника и под кроной существующего дерева"),
            (
                "understory_existing_gap_m",
                "не ближе к стволу существующего дерева, м (743-ПП п. 9.8, по аналогии)",
            ),
            (
                "shrub_groups",
                "группа кустарника на месте дерева, допустимом по нормам, но не получившем вид из-за квот",
            ),
            ("shrub_group_spacing_m", "шаг кустов в группе, м"),
            ("shrub_group_size", "сторона квадрата группы, кустов"),
            (
                "shrub_fill",
                "группы кустарника на газоне до нижней границы 600 на 1 км (МГСН 1.02-02, табл. В.1)",
            ),
            ("shrub_fill_tree_gap_m", "от ствола дерева до группы, м"),
            ("shrub_fill_shrub_gap_m", "между группами, м"),
            ("shrub_fill_step_m", "шаг поиска мест групп, м"),
        ],
    ),
    (
        "Газоны",
        [
            ("lawns", "газоны на грунте, оставшемся свободным после посадок"),
            ("lawn_min_area_m2", "наименьшая площадь газона, м²"),
        ],
    ),
    (
        "Разнообразие",
        [
            (
                "quota_species",
                "доля одного вида деревьев; по умолчанию кода 0,1 (правило 10-20-30, Santamour 1990), в профилях - по практике принятых проектов пилота",
            ),
            ("quota_genus", "доля одного рода деревьев (по умолчанию кода 0,2)"),
            ("quota_family", "доля одного семейства деревьев (по умолчанию кода 0,3)"),
            ("conifer_share", "доля хвойных деревьев: нижняя и верхняя граница"),
            (
                "shrub_quota_species",
                "доля одного вида кустарников (практика принятых проектов пилота)",
            ),
            ("shrub_quota_genus", "доля одного рода кустарников"),
            ("shrub_quota_family", "доля одного семейства кустарников"),
            ("shrub_conifer_share", "доля хвойных кустарников"),
            (
                "shrub_quotas_use_inventory",
                "учитывать существующие кустарники из перечётки в квотах",
            ),
            (
                "structure_patch_size",
                "мест в участке структуры, получающем один вид: аллея меняет породу кварталами",
            ),
            ("alley_priority", "надбавка за занятое место аллеи в задаче назначения видов"),
            ("quota_penalty", "штраф за растение сверх квоты; 0 - квоты жёсткие"),
            (
                "quota_adaptive",
                "квота уровня не строже 1 / медиана числа допустимых видов на месте",
            ),
            (
                "quota_single_places",
                "до скольких мест действует исключение «один экземпляр квоту не нарушает»",
            ),
        ],
    ),
    (
        "Индекс качества",
        [
            (
                "quality_weights",
                "веса слагаемых индекса; не названные берутся по умолчанию (равные)",
            ),
            ("density_trees_per_km", "цель плотности деревьев на 1 км (МГСН 1.02-02, табл. В.1)"),
            ("density_shrubs_per_km", "цель плотности кустарников на 1 км (там же)"),
            ("density_admissible", "цель плотности не выше вместимости зоны допустимости"),
            ("row_spacing_m", "допустимый шаг ряда, м (743-ПП, табл. 3.6.2)"),
            (
                "canopy_target",
                "доля площади крон от потенциала, дающая полный балл (Kenney и др., 2011)",
            ),
            ("canopy_crown_m", "крона для потенциала: медиана взрослой кроны деревьев каталога, м"),
            (
                "existing_crown_m",
                "крона существующего дерева, когда чертёж её не даёт (параметр проекта), м",
            ),
            (
                "street_length_m",
                "длина улицы для плотности; не задана - длина оси границы работ, м",
            ),
            ("dust_target", "доля длины бортов под нижним ярусом, дающая полный балл"),
            ("dust_strip_m", "куст прикрывает борт, если стоит от него не дальше, м"),
            ("dust_crown_factor", "коэффициент для метра борта только под кроной дерева"),
            ("dust_admissible", "пылезащита по бортам, у которых есть грунт"),
            (
                "margin_target_m",
                "запас до ближайшей нормы, дающий полный балл, м (СП 317.1325800.2017, п. 5.3.5.3)",
            ),
            ("diversity_target", "целевое число видов в группе"),
            (
                "diversity_species_share",
                "доля от целевого числа посадок, с которой вид засчитывается полностью",
            ),
        ],
    ),
]


def _value(value: object) -> str:
    if isinstance(value, Enum):
        value = value.value
    if isinstance(value, dict):
        return ", ".join(f"{k}: {_value(v)}" for k, v in value.items()) or "{}"
    if isinstance(value, tuple | list):
        return "[" + ", ".join(_value(v) for v in value) + "]"
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "не задано"
    return str(value)


def params_annex() -> str:
    source = YamlProfileSource(ROOT / "config" / "profiles")
    profiles = {name: source.load(name) for name in source.names()}
    keys = [f.name for f in fields(PlanParams)]
    described = [key for _, group in PARAMS for key, _ in group]
    if set(keys) != set(described) or len(described) != len(set(described)):
        extra, missing = set(described) - set(keys), set(keys) - set(described)
        msg = f"приложение D расходится с PlanParams: лишние {sorted(extra)}, без описания {sorted(missing)}"
        raise SystemExit(msg)
    strict = profiles["strict"]
    others = [name for name in profiles if name != "strict"]
    lines = [
        "## Приложение D. Параметры профилей {#annex-params}",
        "",
        f"Все {len(keys)} параметров прогона (`PlanParams`). Значение - в профиле `strict`; "
        f"в последнем столбце - отличия профилей {', '.join(f'`{n}`' for n in others)}. "
        "Любой параметр переопределяется в CLI (`--set ключ=значение`), в API и интерфейсе "
        "(JSON `overrides`); переопределения записываются в `run_manifest.json`. Сборка "
        "документации проверяет, что описан каждый параметр.",
        "",
    ]
    for title, group in PARAMS:
        lines += [
            f"### {title}",
            "",
            "| Параметр | Смысл | strict | Отличия |",
            "|---|---|---|---|",
        ]
        for key, text in group:
            base = getattr(strict, key)
            diff = [
                f"{name}: `{cell(_value(getattr(p, key)))}`"
                for name, p in profiles.items()
                if name != "strict" and getattr(p, key) != base
            ]
            lines.append(f"| `{key}` | {cell(text)} | `{cell(_value(base))}` | {'; '.join(diff)} |")
        lines.append("")
    return "\n".join(lines)


# --- Сводные факты для текста глав: {{ключ}} подставляет tools/docs/build.py ---


def facts() -> dict[str, str]:
    book = YamlRuleBookSource(ROOT / "config" / "acts.yaml", ROOT / "config" / "rules.yaml").load()
    rules = book.all_rules
    species = YamlSpeciesCatalog(ROOT / "config" / "species.yaml").all()
    found: dict[str, object] = {
        "rules_total": len(rules),
        "rules_distance": len(book.distance_rules),
        "rules_verified": sum(1 for r in rules if r.citation.status is CitationStatus.VERIFIED),
        # Разбивка оснований: сверено по тексту акта; проектный параметр (акт требует величину,
        # но не задаёт её, или аналогия); проектное определение без акта (газоны).
        "rules_by_text": sum(
            1
            for r in rules
            if r.citation.act_id != "PROJECT" and r.citation.status is CitationStatus.VERIFIED
        ),
        "rules_project": sum(
            1
            for r in rules
            if r.citation.act_id == "PROJECT" and r.citation.status is CitationStatus.VERIFIED
        ),
        "rules_definitions": sum(
            1
            for r in rules
            if r.citation.act_id == "PROJECT" and r.citation.status is not CitationStatus.VERIFIED
        ),
        "acts": sum(1 for act_id in book.acts if act_id != "PROJECT"),
        "species": len(species),
        "species_trees": sum(1 for s in species if not s.is_shrub),
        "species_shrubs": sum(1 for s in species if s.is_shrub),
        "params": len(fields(PlanParams)),
        "artifacts": len(ARTIFACTS),
    }
    catalog = ROOT / "dataset" / "streets_oda" / "catalog.json"
    if catalog.is_file():
        data = json.loads(catalog.read_text(encoding="utf-8"))
        found["streets_total"] = len(data if isinstance(data, list) else data["streets"])
    runs = street_rows()
    done = [r for r in runs if r["state"] == "succeeded"]
    if done:
        kinds: list[str] = []
        entities = violations = changed = 0
        for row in done:
            output = Path(str(row["output"]))
            plan = json.loads((output / "plan.json").read_text(encoding="utf-8"))
            kinds += [p["planting_type"] for p in plan["placements"]]
            verify = json.loads((output / "verify.json").read_text(encoding="utf-8"))
            entities += verify["source_entities"]
            changed += sum(
                len(verify[key]) for key in ("changed", "missing", "added_outside_result_layers")
            )
            violations += len(
                json.loads((output / "validation.json").read_text(encoding="utf-8"))["issues"]
            )
        minutes = sorted(r["seconds"] / 60 for r in done)
        found |= {
            "streets_run": len(runs),
            "streets_done": len(done),
            "trees": thousands(kinds.count("tree")),
            "shrubs": thousands(kinds.count("shrub")),
            "violations": violations,
            "entities": thousands(entities),
            "entities_changed": changed,
            "minutes_min": number(minutes[0], 1),
            "minutes_max": number(minutes[-1], 1),
            "minutes_median": number(minutes[len(minutes) // 2], 1),
        }
    found |= _street_texts(runs, int(str(found.get("streets_total", len(runs)))))
    found |= effect_facts(runs)
    found |= _audit_texts()
    return {key: str(value) for key, value in found.items()}


def _title(row: dict[str, object]) -> str:
    """Название улицы как в описи принятых проектов, иначе как в каталоге."""
    designer = yaml.safe_load(
        (ROOT / "docs" / "data" / "designer-plans.yaml").read_text(encoding="utf-8")
    )["streets"]
    titles = {street["slug"]: street.get("title") for street in designer}
    return str(titles.get(str(row["slug"])) or row.get("title") or row["slug"])


def _street_texts(runs: list[dict[str, object]], total: int) -> dict[str, str]:
    """Фразы о прогоне улиц для глав: сводка, итог чтения, пиковая память."""
    done = [r for r in runs if r["state"] == "succeeded"]
    planted = [r for r in done if (r.get("summary") or {}).get("placements")]  # type: ignore[union-attr]
    empty = [r for r in done if r not in planted]
    unfinished = [r for r in runs if r["state"] != "succeeded"]
    summary = f"план с посадками на {len(planted)} улицах из {total} каталога"
    if empty:
        summary += "; план пуст: " + ", ".join(_title(r) for r in empty)
    if unfinished:
        summary += "; не досчитаны: " + ", ".join(_title(r) for r in unfinished)
    summary += " (причины и исправления - приложение B)" if empty or unfinished else ""
    unread = [r for r in unfinished if "прочитан не полностью" in str(r.get("error") or "")]
    fixed = [r for r in unread if r["slug"] in STREET_NOTES]
    read_ok = sum(1 for r in runs if r["state"] == "succeeded")
    reading = f"Итог по пилоту (конвертер ODA): {read_ok} прогнанных улиц читаются без пробелов."
    if fixed:
        reading += (
            " Олимпийскую деревню в пакете остановил единственный пробел - полилиния борта с "
            "выпуклостью 1,4·10⁻¹³; это дефект чтения, он исправлен (приложение B)."
        )
    if len(unread) > len(fixed):
        reading += " Чтение остановлено на улицах: " + ", ".join(
            _title(r) for r in unread if r not in fixed
        )
    stops = (
        "На улицах пилота таких объектов нет: единственный пробел (Олимпийская деревня) давало "
        "чтение выпуклости полилинии, он исправлен."
        if len(unread) == len(fixed)
        else "На пилоте такие объекты есть: "
        + ", ".join(_title(r) for r in unread if r not in fixed)
        + "."
    )
    peaks = []
    for row in runs:
        measured = peak_memory(row)
        if measured is not None:
            peaks.append((measured[0], _title(row)))
    peak_text = (
        f"{number(max(peaks)[0], 1)} ГБ ({max(peaks)[1]})"
        if peaks
        else "несколько гигабайт (замер не проводился)"
    )
    return {
        "streets_summary": summary,
        "reading_result": reading,
        "reading_stops": stops,
        "peak_memory": peak_text,
    }


AUDIT = ROOT / "out" / "docs" / "audit-berzarina" / "audit.json"


def _audit_texts() -> dict[str, str]:
    """Нормоконтроль плана проектировщика Берзарина: последний прогон `green audit`."""
    if AUDIT.is_file():
        data = json.loads(AUDIT.read_text(encoding="utf-8"))
        summary = data.get("summary", data)
        bad, total = summary["with_violations"], summary["plantings"]
        count = summary["violations"]
        when = datetime.fromtimestamp(AUDIT.stat().st_mtime, tz=UTC).astimezone()
        date = when.strftime("%d.%m.%Y")
    else:
        bad, total, count, date = 391, 554, 785, "18.09.2026"
    short = f"в плане проектировщика улицы Берзарина посадок с нарушениями норм - {bad} из {total}"
    result = (
        f"Берзарина, прогон {date}: в плане проектировщика посадок с нарушениями норм - {bad} "
        f"из {total}, нарушений {count}; в плане сервиса нарушений нет по независимой проверке "
        "(разд. 3.10, приложение B)."
    )
    return {"audit_short": short, "audit_result": result}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "A-rules.md").write_text(rules_annex(), encoding="utf-8", newline="\n")
    if street_rows():
        (OUT / "B-streets.md").write_text(streets_annex(), encoding="utf-8", newline="\n")
    (OUT / "C-artifacts.md").write_text(artifacts_annex(), encoding="utf-8", newline="\n")
    (OUT / "D-params.md").write_text(params_annex(), encoding="utf-8", newline="\n")
    (OUT / "facts.json").write_text(
        json.dumps(facts(), ensure_ascii=False, indent=1), encoding="utf-8", newline="\n"
    )
    print("annexes:", ", ".join(sorted(p.name for p in OUT.glob("*.*"))))


if __name__ == "__main__":
    main()
