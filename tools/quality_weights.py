"""Веса индекса качества по анкетам экспертов (метод анализа иерархий Саати).

    uv run python tools/quality_weights.py docs/quality-ahp-example.yaml

Анкета и порядок суждений - docs/quality-weights.md. Скрипт печатает веса каждого эксперта с
отношением согласованности CR, веса панели (геометрическое среднее суждений) и строки
quality_weights для профиля. Эксперт с CR >= 0,1 в панель не входит: его анкету надо вернуть.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

from green.application.quality.weights import CR_LIMIT, expert_weights, panel_weights


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("forms", type=Path, help="YAML с анкетами: experts -> имя -> суждения")
    args = parser.parse_args()
    data = yaml.safe_load(args.forms.read_text(encoding="utf-8"))
    forms = data["experts"]

    accepted = {}
    for name, form in forms.items():
        expert = expert_weights(name, form)
        crs = [expert.groups.cr, *(p.cr for p in expert.within.values())]
        mark = "ок" if expert.consistent else f"CR >= {CR_LIMIT}: вернуть эксперту"
        print(f"{name}: CR групп {expert.groups.cr:.3f}, худший CR {max(crs):.3f} - {mark}")
        print("   " + ", ".join(f"{k} {v:.3f}" for k, v in expert.terms.items()))
        if expert.consistent:
            accepted[name] = form
    if not accepted:
        sys.exit("ни одной согласованной анкеты")

    panel = panel_weights(accepted)
    print(f"\nПанель ({len(accepted)} из {len(forms)}), CR групп {panel.groups.cr:.3f}:")
    print("quality_weights:")
    for key, value in panel.terms.items():
        print(f"  {key}: {value}")


if __name__ == "__main__":
    main()
