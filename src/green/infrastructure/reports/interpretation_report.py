"""Читаемый отчёт интерпретаций: Markdown, HTML для печати в PDF и CSV «одна строка - посадка».

`interpretations.csv` и `.json` - полная трасса: строка на пару «решение - правило», их читает
программа или эксперт с фильтром. Этот отчёт читается глазами: по каждой посадке определяющая
норма - проверка с наименьшим запасом (так же выбирает «Ближайшие ограничения» объяснение и
«Ближе всего к норме» интерфейс), расстояние, норма, запас и основание с актом и пунктом; по
отказу - нарушенные нормы; по газону - основание. Полный текст объяснения посадки - в
`plantings.csv`, одной строкой на посадку.
"""

from __future__ import annotations

import csv
import html
from dataclasses import dataclass
from typing import TYPE_CHECKING

from green.application.explain import (
    CROWN_NOTE,
    LAWN_LABELS,
    OBJECT_LABELS,
    VERDICT_LABELS,
    crown_increment_m,
)
from green.application.places import PLACE_LABELS
from green.domain.planting import CheckOutcome

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence
    from pathlib import Path

    from green.application.results import RunReport
    from green.domain.effect import StreetEffect
    from green.domain.norms import AnyRule, RuleBook
    from green.domain.planting import Placement, Plan, Rejection, RuleCheck

PLANTINGS_COLUMNS = (
    "number",
    "id",
    "planting_type",
    "species_ru",
    "species_lat",
    "x",
    "y",
    "verdict",
    "place",
    "governing_rule",
    "governing_object",
    "measured_m",
    "threshold_m",
    "margin_m",
    "act",
    "clause",
    "checks",
    "explanation",
)
_TYPE = {"tree": "дерево", "shrub": "кустарник", "lawn": "газон"}


@dataclass(frozen=True, slots=True)
class _Norm:
    """Проверка, прочитанная для человека: что, сколько, сколько надо, по какому акту."""

    rule_id: str
    target: str
    measured: float | None
    threshold: float | None
    act: str
    clause: str
    # Прирост нормы за крону шире 5 м (прим. 1 к табл. 9.1 СП 42.13330), 0 - норма из таблицы.
    crown_extra: float = 0.0

    @property
    def crown_split(self) -> str:
        """Из чего сложена норма с приростом за крону: « = 2,00 + 1,00 за крону». Без разбивки
        норма 3,00 при 2,0 в табл. 9.1 читается как ошибка. Без прироста - пусто."""
        if self.threshold is None or not self.crown_extra:
            return ""
        base = self.threshold - self.crown_extra
        return f" = {_m(base)} + {_m(self.crown_extra)} за крону"

    @property
    def margin(self) -> float | None:
        if self.measured is None or self.threshold is None:
            return None
        return self.measured - self.threshold


class _Rules:
    def __init__(self, rulebook: RuleBook) -> None:
        self.book = rulebook
        self.by_id: dict[str, AnyRule] = {r.rule_id: r for r in rulebook.all_rules}

    def norm(self, check: RuleCheck) -> _Norm:
        rule = self.by_id.get(check.rule_id)
        act = self.book.label_of(rule.citation.act_id) if rule else ""
        clause = rule.citation.clause if rule else "правило отсутствует в базе"
        if rule is not None:
            # Действующая редакция СП 42 рядом с названной в ТЗ: эксперт находит пункт в обеих.
            current = [r for r in rule.citation.related if r.act_id == "SP42_13330_2026"]
            if current:
                clause += f" (ред. 2026: {current[0].clause.split(':')[0]})"
        label = OBJECT_LABELS.get(check.object_class, str(check.object_class or ""))
        target = f"до {label}" if label else ""
        return _Norm(
            check.rule_id,
            target,
            check.measured_m,
            check.threshold_m,
            act,
            clause,
            crown_increment_m(check, rule),
        )


def governing(placement: Placement, rules: _Rules) -> _Norm | None:
    """Определяющая норма посадки: измеренная проверка с наименьшим запасом."""
    measured = [c for c in placement.checks if c.measured_m is not None]
    if not measured:
        return None
    closest = min(measured, key=lambda c: (c.measured_m or 0.0) - (c.threshold_m or 0.0))
    return rules.norm(closest)


def _violations(rejection: Rejection, rules: _Rules) -> list[_Norm]:
    return [
        rules.norm(c)
        for c in rejection.blocking
        if c.outcome in (CheckOutcome.FAIL, CheckOutcome.BARRIER)
    ]


def _m(value: float | None) -> str:
    return "" if value is None else f"{value:.2f}".replace(".", ",")


def _xy(value: float) -> str:
    return f"{value:.2f}".replace(".", ",")


def _acts(plan: Plan, rules: _Rules) -> list[tuple[str, str, str]]:
    """Акты, на которые опирается план, с редакцией и ссылкой на текст."""
    used: set[str] = set()
    checks: Iterable[RuleCheck] = (
        *(c for p in plan.placements for c in p.checks),
        *(c for r in plan.rejections for c in r.blocking),
    )
    for check in checks:
        rule = rules.by_id.get(check.rule_id)
        if rule is not None:
            used.update(rule.citation.act_ids)
    for lawn in plan.lawns:
        for rule_id in lawn.rule_ids:
            rule = rules.by_id.get(rule_id)
            if rule is not None:
                used.update(rule.citation.act_ids)
    rows = []
    for act_id in sorted(used):
        act = rules.book.acts.get(act_id)
        if act is not None:
            rows.append((act.title, act.edition, act.url))
    return rows


def _header(report: RunReport) -> list[tuple[str, str]]:
    plan = report.plan
    allowed = sum(1 for p in plan.placements if p.verdict.value == "allowed")
    lawn_m2 = sum(g.area_m2 for g in plan.lawns)
    return [
        ("Чертёж", report.source_name),
        ("Прогон", report.run_id),
        ("Профиль норм", report.profile),
        ("Редакция СП 42.13330", report.params.sp42_edition),
        (
            "Посадок",
            (
                f"{len(plan.placements)}: допускается {allowed}, требует согласования "
                f"{len(plan.placements) - allowed}"
            ),
        ),
        ("Отказов", str(len(plan.rejections))),
        ("Газонов", f"{len(plan.lawns)}, {_m(lawn_m2)} м²"),
        ("Исходные слои", "не изменены" if report.integrity.ok else "ИЗМЕНЕНЫ"),
        ("Исходный файл, SHA-256", report.source_sha256),
        ("Свод правил, отпечаток", report.rulebook.fingerprint[:16]),
    ]


_HOW = (
    "Определяющая норма посадки - проверка с наименьшим запасом: измеренное расстояние минус "
    "норма. Все остальные проверки посадки выполнены с большим запасом. Полная трасса - "
    "interpretations.csv (строка на пару «посадка - правило»), полный текст объяснения - "
    "plantings.csv."
)


def _how(plan: Plan, rules: _Rules) -> str:
    """Пояснение к таблице посадок; если у норм есть прирост за крону - его основание."""
    raised = any(
        crown_increment_m(check, rules.by_id.get(check.rule_id))
        for p in plan.placements
        for check in p.checks
        if check.measured_m is not None
    )
    if not raised:
        return _HOW
    return (
        f"{_HOW} Норма со слагаемым «за крону» - норма табл. 9.1 и прирост за крону шире 5 м."
        f"{CROWN_NOTE}, прирост - толкование проекта (crown_extra_per_m)."
    )


def _placement_row(p: Placement, rules: _Rules) -> list[str]:
    norm = governing(p, rules)
    return [
        str(p.number),
        f"{p.species.name_ru} ({p.species.name_lat})",
        _TYPE.get(p.planting_type.value, p.planting_type.value),
        _xy(p.x),
        _xy(p.y),
        VERDICT_LABELS[p.verdict],
        f"{norm.target} ({norm.rule_id})" if norm else "",
        _m(norm.measured) if norm else "",
        _m(norm.threshold) + norm.crown_split if norm else "",
        _m(norm.margin) if norm else "",
        f"{norm.act}, {norm.clause}" if norm else "",
    ]


def _rejection_row(r: Rejection, rules: _Rules) -> list[str]:
    broken = _violations(r, rules)
    what = "; ".join(
        f"{n.target}: {_m(n.measured)} м < {_m(n.threshold)} м{n.crown_split} ({n.rule_id})"
        for n in broken
    )
    basis = "; ".join(f"{n.act}, {n.clause}" for n in broken)
    if r.note and not broken:
        what, basis = r.note, "состав плана: квоты разнообразия"
    return [
        str(r.number),
        _TYPE.get(r.planting_type.value, r.planting_type.value),
        _xy(r.x),
        _xy(r.y),
        VERDICT_LABELS[r.verdict],
        what,
        basis,
    ]


def _lawn_rows(plan: Plan, rules: _Rules) -> list[list[str]]:
    rows = []
    for lawn in plan.lawns:
        basis = "; ".join(
            f"{rules.book.label_of(rule.citation.act_id)}, {rule.citation.clause}"
            for rule_id in lawn.rule_ids
            if (rule := rules.by_id.get(rule_id)) is not None
        )
        rows.append([str(lawn.number), LAWN_LABELS[lawn.kind], _m(lawn.area_m2), basis])
    return rows


PLACEMENT_HEAD = (
    "№",
    "Вид",
    "Тип",
    "X",
    "Y",
    "Решение",
    "Определяющая норма",
    "Расстояние, м",
    "Норма, м",
    "Запас, м",
    "Основание",
)
REJECTION_HEAD = ("№", "Тип", "X", "Y", "Решение", "Нарушено", "Основание")
LAWN_HEAD = ("№", "Газон", "Площадь, м²", "Основание")
EFFECT_HEAD = ("Показатель", "Было", "Стало", "Изменение", "Основание", "Пояснение")
KIND_HEAD = ("Вид посадки", "Штук", "Пог. м", "Площадь, м²", "Место", "Основание термина")
NOISE_HEAD = ("Ширина полосы, м", "Снижение по МГСН, дБА", "По СП 276, дБА", "Было, м", "Стало, м")
_EFFECT_HOW = (
    "Было - существующие насаждения чертежа (или перечётной ведомости), стало - они вместе с "
    "посадками плана. Вырубку и пересадку сервис не назначает: существующие насаждения "
    "сохраняются. Показатели - те, что заказчик назвал признаками хорошего плана: тень, "
    "пылезащита, многоярусность, разнообразие; у каждого основание и пояснение, что считается."
)


_WHOLE_FROM = 100  # от сотни дробная часть в отчёте лишняя


def _num(value: float | None, unit: str = "") -> str:
    if value is None:
        return "-"
    whole = abs(value) >= _WHOLE_FROM
    text = f"{value:,.0f}".replace(",", " ") if whole else f"{value:g}".replace(".", ",")
    return f"{text} {unit}".strip()


def _effect_rows(effect: StreetEffect) -> list[list[str]]:
    rows = []
    for m in effect.measures:
        delta = m.delta
        sign = "+" if delta is not None and delta > 0 else ""
        rows.append(
            [
                m.title,
                _num(m.before, m.unit),
                _num(m.after, m.unit),
                f"{sign}{_num(delta, m.unit)}" if delta is not None else "-",
                m.basis,
                m.note,
            ]
        )
    return rows


def _kind_rows(effect: StreetEffect) -> list[list[str]]:
    return [
        [
            k.title,
            str(k.count) if k.planting_type != "lawn" else "-",
            _num(k.length_m),
            _num(k.area_m2),
            _places(k.places),
            k.basis,
        ]
        for k in effect.kinds
    ]


def _places(places: Mapping[str, int]) -> str:
    known = {k: n for k, n in places.items() if k in PLACE_LABELS and k != "unknown"}
    if not known:
        return "-" if not places else "не определено"
    return ", ".join(
        f"{PLACE_LABELS[k]} {n}" for k, n in sorted(known.items(), key=lambda x: -x[1])
    )


def _noise_rows(effect: StreetEffect) -> list[list[str]]:
    return [
        [b.width, b.dba, b.dba_sp276, _num(b.curb_before_m), _num(b.curb_after_m)]
        for b in effect.noise
    ]


def _md_table(head: Sequence[str], rows: Iterable[Sequence[str]]) -> list[str]:
    def cell(value: str) -> str:
        return value.replace("|", "/").replace("\n", " ")

    lines = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    lines += ["| " + " | ".join(cell(v) for v in row) + " |" for row in rows]
    return lines


def write_markdown(path: Path, report: RunReport) -> Path:
    rules = _Rules(report.rulebook)
    plan = report.plan
    lines = [f"# Интерпретация плана посадок: {report.source_name}", ""]
    lines += [f"- {name}: {value}" for name, value in _header(report)]
    if plan.effect is not None:
        lines += ["", "## Баланс озеленения и эффект", "", _EFFECT_HOW, ""]
        lines += _md_table(EFFECT_HEAD, _effect_rows(plan.effect))
        lines += ["", "Шумозащита: борта с полосой насаждений от 10 м", ""]
        lines += _md_table(NOISE_HEAD, _noise_rows(plan.effect))
        lines += [f"- {note}" for note in plan.effect.notes]
        lines += ["", "## Виды посадок", ""]
        lines += _md_table(KIND_HEAD, _kind_rows(plan.effect))
    lines += ["", "## Нормативная база", ""]
    lines += _md_table(("Акт", "Редакция и сверка", "Текст"), _acts(plan, rules))
    lines += ["", "## Посадки", "", _how(plan, rules), ""]
    lines += _md_table(PLACEMENT_HEAD, (_placement_row(p, rules) for p in plan.placements))
    lines += ["", "## Отказы", ""]
    lines += _md_table(REJECTION_HEAD, (_rejection_row(r, rules) for r in plan.rejections))
    if plan.lawns:
        lines += ["", "## Газоны", ""]
        lines += _md_table(LAWN_HEAD, _lawn_rows(plan, rules))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return path


_CSS = """
@page { size: A4 landscape; margin: 12mm 10mm; }
body { font: 9pt/1.35 "DejaVu Sans", "Segoe UI", Arial, sans-serif; color: #1d1d1b; }
h1 { font-size: 15pt; margin: 0 0 6pt; }
h2 { font-size: 12pt; margin: 14pt 0 6pt; break-after: avoid; }
dl { display: grid; grid-template-columns: max-content 1fr; gap: 2pt 12pt; margin: 0; }
dt { color: #5b5b55; }
dd { margin: 0; }
p.how { color: #3c3c38; max-width: 190mm; }
table { border-collapse: collapse; width: 100%; }
thead { display: table-header-group; }
tr { break-inside: avoid; }
th, td { border: 0.5pt solid #b9b6aa; padding: 2pt 4pt; text-align: left; vertical-align: top; }
th { background: #efece2; font-weight: 600; }
td.n { text-align: right; white-space: nowrap; font-variant-numeric: tabular-nums; }
"""
_NUMERIC = {
    "№",
    "X",
    "Y",
    "Расстояние, м",
    "Норма, м",
    "Запас, м",
    "Площадь, м²",
    "Было",
    "Стало",
    "Изменение",
    "Штук",
    "Пог. м",
    "Было, м",
    "Стало, м",
}


def _html_table(head: Sequence[str], rows: Iterable[Sequence[str]]) -> str:
    numeric = [name in _NUMERIC for name in head]
    parts = ["<table><thead><tr>"]
    parts += [f"<th>{html.escape(name)}</th>" for name in head]
    parts.append("</tr></thead><tbody>")
    for row in rows:
        parts.append("<tr>")
        for value, is_number in zip(row, numeric, strict=True):
            klass = ' class="n"' if is_number else ""
            parts.append(f"<td{klass}>{html.escape(value)}</td>")
        parts.append("</tr>")
    parts.append("</tbody></table>")
    return "".join(parts)


def _effect_html(effect: StreetEffect | None) -> list[str]:
    if effect is None:
        return []
    notes = "".join(f'<p class="how">{html.escape(n)}</p>' for n in effect.notes)
    return [
        f'<h2>Баланс озеленения и эффект</h2><p class="how">{html.escape(_EFFECT_HOW)}</p>',
        _html_table(EFFECT_HEAD, _effect_rows(effect)),
        "<h2>Шумозащита: борта с полосой насаждений от 10 м</h2>",
        _html_table(NOISE_HEAD, _noise_rows(effect)),
        notes,
        "<h2>Виды посадок</h2>",
        _html_table(KIND_HEAD, _kind_rows(effect)),
    ]


def write_html(path: Path, report: RunReport) -> Path:
    """Тот же отчёт в HTML: открывается в браузере и печатается в PDF на A4 без доработки."""
    rules = _Rules(report.rulebook)
    plan = report.plan
    title = f"Интерпретация плана посадок: {report.source_name}"
    header = "".join(
        f"<dt>{html.escape(name)}</dt><dd>{html.escape(value)}</dd>"
        for name, value in _header(report)
    )
    body = [
        f"<h1>{html.escape(title)}</h1><dl>{header}</dl>",
        *_effect_html(plan.effect),
        "<h2>Нормативная база</h2>",
        _html_table(("Акт", "Редакция и сверка", "Текст"), _acts(plan, rules)),
        f'<h2>Посадки</h2><p class="how">{html.escape(_how(plan, rules))}</p>',
        _html_table(PLACEMENT_HEAD, (_placement_row(p, rules) for p in plan.placements)),
        "<h2>Отказы</h2>",
        _html_table(REJECTION_HEAD, (_rejection_row(r, rules) for r in plan.rejections)),
    ]
    if plan.lawns:
        body += ["<h2>Газоны</h2>", _html_table(LAWN_HEAD, _lawn_rows(plan, rules))]
    document = (
        '<!doctype html><html lang="ru"><head><meta charset="utf-8">'
        f"<title>{html.escape(title)}</title><style>{_CSS}</style></head>"
        f"<body>{''.join(body)}</body></html>"
    )
    path.write_text(document, encoding="utf-8", newline="\n")
    return path


def write_plantings_csv(path: Path, report: RunReport) -> Path:
    """Одна строка на посадку: для таблицы в Excel без фильтра по номеру."""
    rules = _Rules(report.rulebook)
    texts = {e.subject_id: e.text for e in report.plan.explanations}
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream, delimiter=";")
        writer.writerow(PLANTINGS_COLUMNS)
        for p in report.plan.placements:
            norm = governing(p, rules)
            writer.writerow(
                [
                    p.number,
                    p.placement_id,
                    p.planting_type.value,
                    p.species.name_ru,
                    p.species.name_lat,
                    round(p.x, 3),
                    round(p.y, 3),
                    p.verdict.value,
                    PLACE_LABELS.get(p.place or "unknown", p.place),
                    norm.rule_id if norm else "",
                    norm.target if norm else "",
                    round(norm.measured, 3) if norm and norm.measured is not None else "",
                    norm.threshold if norm and norm.threshold is not None else "",
                    round(norm.margin, 3) if norm and norm.margin is not None else "",
                    norm.act if norm else "",
                    norm.clause if norm else "",
                    len(p.checks),
                    texts.get(p.placement_id, ""),
                ]
            )
    return path
