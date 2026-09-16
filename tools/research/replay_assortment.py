"""Повторить подбор ассортимента по готовому прогону без чтения DXF.

Размещение и измеренные расстояния берутся из plan.json прогона, существующие деревья - из
assortment.json. Подбор видов считается заново по текущим config/rules.yaml,
config/species.yaml и профилю. Нужен, чтобы проверить правку каталога или профиля за
секунды, а не за три минуты полного прогона, и чтобы результат можно было воспроизвести.

Во входном plan.json должны быть все места размещения: брать прогон, где места без вида ещё
не переносились в отказы, либо любой прогон, если таких мест не было.

    uv run python tools/research/replay_assortment.py out/check/berzarina_norms --profile strict
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from green.application.assortment import assign_species
from green.application.assortment.context import site_context
from green.application.assortment.filters import species_verdict
from green.domain.norms import PlantingType
from green.domain.objects import ObjectClass
from green.domain.planting import CheckOutcome, Placement, Plan, RuleCheck, Verdict
from green.infrastructure.config.repositories import (
    YamlProfileSource,
    YamlRuleBookSource,
    YamlSpeciesCatalog,
)

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "config"


def _placements(plan: dict, catalog: YamlSpeciesCatalog, default: str) -> tuple[Placement, ...]:
    species = catalog.get(default)
    return tuple(
        Placement(
            placement_id=item["id"],
            number=item["number"],
            planting_type=PlantingType(item["planting_type"]),
            species=species,
            x=item["x"],
            y=item["y"],
            verdict=Verdict(item["verdict"]),
            checks=tuple(
                RuleCheck(
                    rule_id=check["rule_id"],
                    outcome=CheckOutcome(check["outcome"]),
                    threshold_m=check["threshold_m"],
                    measured_m=check["measured_m"],
                    object_class=ObjectClass(check["object_class"])
                    if check["object_class"]
                    else None,
                )
                for check in item["checks"]
            ),
            notes=tuple(item["notes"]),
        )
        for item in plan["placements"]
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("run", type=Path, help="каталог прогона с plan.json и assortment.json")
    parser.add_argument("--profile", default="strict")
    parser.add_argument(
        "--why", nargs="*", default=[], metavar="FAMILY", help="три главные причины отказа видов"
    )
    args = parser.parse_args()

    plan_data = json.loads((args.run / "plan.json").read_text(encoding="utf-8"))
    existing = json.loads((args.run / "assortment.json").read_text(encoding="utf-8"))["existing"]
    rulebook = YamlRuleBookSource(CONFIG / "acts.yaml", CONFIG / "rules.yaml").load()
    catalog = YamlSpeciesCatalog(CONFIG / "species.yaml")
    params = YamlProfileSource(CONFIG / "profiles").load(args.profile)
    placements = _placements(plan_data, catalog, params.species_code)

    plan = assign_species(
        Plan(placements=placements, rejections=()), rulebook, catalog.all(), params, existing
    )
    summary = plan.assortment_summary
    assert summary is not None  # noqa: S101 - подбор всегда даёт сводку

    # Сколько мест каждого приёма занято и какие семейства вообще допустимы по нормам.
    mode = {p.placement_id: (p.notes[0] if p.notes else "") for p in placements}
    planted = Counter(mode[p.placement_id] for p in plan.placements)
    total = Counter(mode.values())
    families: Counter[str] = Counter()
    for placement in placements:
        ctx = site_context(placement)
        allowed = {
            s.family
            for s in catalog.all()
            if s.is_tree and species_verdict(s, ctx, rulebook, params).allowed
        }
        families.update(allowed)

    print(f"мест: {len(placements)}, занято: {len(plan.placements)}, в отказах: {summary.no_species}")
    for name, count in total.items():
        print(f"  {name}: занято {planted[name]} из {count}")
    print(f"видов: {len(summary.counts)}, Шеннон: {summary.shannon}, хвойных: {summary.conifer_share:.3f}")
    print(f"нарушения квот: {list(summary.quota_violations) or 'нет'}")
    print("состав:", dict(sorted(summary.counts.items(), key=lambda kv: -kv[1])))
    print("доли семейств:", summary.family_shares)
    print("в скольких местах семейство допустимо по нормам:", dict(families.most_common()))
    for note in summary.notes:
        print("заметка:", note)
    _why(placements, catalog, rulebook, params, set(args.why))


def _why(placements, catalog, rulebook, params, families: set[str]) -> None:  # noqa: ANN001
    """По каждому виду названных семейств: какие правила чаще всего его отсекают."""
    if not families:
        return
    reasons: dict[str, Counter[str]] = {}
    for placement in placements:
        ctx = site_context(placement)
        for species in catalog.all():
            if not species.is_tree or species.family not in families:
                continue
            verdict = species_verdict(species, ctx, rulebook, params)
            blocking = verdict.blocking
            if blocking is None:
                continue
            label = blocking.rule_id or blocking.text[:40]
            if "увеличен" in blocking.text:
                label += " (увеличение за крону)"
            reasons.setdefault(species.code, Counter())[label] += 1
    for code, counter in sorted(reasons.items()):
        print(f"почему не {code}:", counter.most_common(3))


if __name__ == "__main__":
    main()
