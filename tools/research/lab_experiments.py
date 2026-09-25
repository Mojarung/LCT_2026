"""Варианты пайплайна посадок для стенда pipeline_lab (docs/notes/30-pipeline-experiments.md).

Каждый эксперимент - последовательность этапов и поправки параметров. E00 повторяет сервис
как есть; остальные меняют по одному рычагу, чтобы было видно, что именно дало прирост.
Индекс всегда меряется параметрами профиля без поправок эксперимента (Lab.ruler).
"""

from __future__ import annotations

from lab_stages import curb_hedges, gap_fill, hill_climb, prune, shrub_fill, stage, understory
from pipeline_lab import (
    BASE,
    SERVICE,
    understory as understory_src,
    Experiment,
    assort,
    experiment,
    place,
    quality,
    refine,
    shrub_groups,
    shrub_rows,
)

# --- A. Базовый сервис и что даёт каждый его этап --------------------------------------------
# Сервис до 23.09.2026: исключение «один экземпляр» в квотах - только для плана меньше 10 мест.
OLD = {"quota_single_places": 1.0}
experiment(Experiment("E00", "сервис как есть: аллея+газон, виды, группы, ряд, сдвиг",
                      overrides=OLD))
experiment(Experiment("E01", "просто посадить: аллея+газон и виды, без кустарников и сдвига",
                      stages=(place, assort, quality)))
experiment(Experiment("E02", "E01 + сдвиг слабых мест", stages=(place, assort, quality, refine)))
experiment(Experiment("E03", "E01 + группы кустарников на пустых местах",
                      stages=(place, assort, shrub_groups, quality)))
experiment(Experiment("E04", "E01 + ряд кустарника у борта под аллеей",
                      stages=(place, assort, shrub_rows, quality)))

# --- B. Деревья: больше мест и лучше места ----------------------------------------------------
GAP = stage(gap_fill, "gap_fill")
GAP_SLACK = stage(gap_fill, "gap_fill_slack", order="slack")
experiment(Experiment("E05", "шаг посадки 5 м вместо 6 (743-ПП, табл. 3.6.2: 5-6 м)",
                      overrides={"spacing_m": 5.0}))
experiment(Experiment("E06", "E00 + добор зоны мелкой сеткой 1 м (построчно)",
                      stages=(place, GAP, assort, shrub_groups, shrub_rows, quality, refine)))
experiment(Experiment("E07", "E00 + добор зоны, сначала места с запасом до сетей",
                      stages=(place, GAP_SLACK, assort, shrub_groups, shrub_rows, quality, refine)))
experiment(Experiment("E08", "отступы аллеи от борта 2,5/3,0/2,0 вместо 2,0/2,5/3,0",
                      overrides={"curb_offsets_m": [2.5, 3.0, 2.0]}))

# --- C. Кустарники: ярус, пылезащита, плотность -------------------------------------------------
HEDGES = stage(curb_hedges, "curb_hedges")
HEDGES_TALL = stage(curb_hedges, "curb_hedges_1m", spacing_m=1.0)
HEDGES_HALF = stage(curb_hedges, "curb_hedges_half", spacing_m=1.0, max_share=0.5)
UNDER = stage(understory, "understory")
UNDER_ALL = stage(understory, "understory_all", which="all")
experiment(Experiment("E09", "E00 + изгородь вдоль всех бортов с грунтом, шаг 0,4 м",
                      stages=(*BASE[:4], HEDGES, quality, refine)))
experiment(Experiment("E10", "E00 + изгородь вдоль всех бортов, высокий кустарник шаг 1 м",
                      stages=(*BASE[:4], HEDGES_TALL, quality, refine)))
experiment(Experiment("E11", "E00 + группа кустарника под кроной каждого дерева аллеи",
                      stages=(*BASE[:4], UNDER, quality, refine)))
experiment(Experiment("E12", "E00 + группа кустарника под кроной любого дерева",
                      stages=(*BASE[:4], UNDER_ALL, quality, refine)))

# --- D. Ассортимент ---------------------------------------------------------------------------
experiment(Experiment("E13", "квоты 10-20-30 мягкие при подборе (место не пустует); индекс - прежний",
                      overrides={"quota_species": 1.0, "quota_genus": 1.0, "quota_family": 1.0}))
experiment(Experiment("E14", "подбор: вес категории В.6 0,20 -> 0,40",
                      overrides={"assortment_weights": {"site": 0.30, "function": 0.20,
                                                        "decor": 0.15, "longevity": 0.15,
                                                        "care": 0.10, "pilot": 0.10,
                                                        "category": 0.40}}))
experiment(Experiment("E15", "участок ряда при подборе 10 -> 5 деревьев",
                      overrides={"structure_patch_size": 5}))

# --- E. Удаление слабых (для сравнения, в сервис не пойдёт без причины) -----------------------
experiment(Experiment("E16", "E00 + удалить посадки с отрицательным вкладом",
                      stages=(*BASE, stage(prune, "prune"))))

# --- F. Подбор знает об аллее --------------------------------------------------------------
experiment(Experiment("E17", "подбор: надбавка местам аллеи +2 (пустеет газон, не аллея)",
                      overrides={"alley_priority": 2.0}))
experiment(Experiment("E18", "подбор: надбавка местам аллеи +5", overrides={"alley_priority": 5.0}))

# --- G. Сочетания лучших рычагов ------------------------------------------------------------
PRIORITY = {"alley_priority": 2.0}
experiment(Experiment("E19", "шаг 5 м + надбавка аллее + куст под кроной аллеи",
                      stages=(*BASE[:4], UNDER, quality, refine),
                      overrides={"spacing_m": 5.0, **PRIORITY}))
experiment(Experiment("E20", "E19 + добор зоны с приоритетом запаса",
                      stages=(place, GAP_SLACK, assort, shrub_groups, shrub_rows, UNDER, quality,
                              refine),
                      overrides={"spacing_m": 5.0, **PRIORITY}))
experiment(Experiment("E21", "E20 + изгородь у всех бортов шагом 1 м",
                      stages=(place, GAP_SLACK, assort, shrub_groups, shrub_rows, HEDGES_TALL,
                              UNDER, quality, refine),
                      overrides={"spacing_m": 5.0, **PRIORITY}))

# --- H. «Посадить - подвигать - досадить - подвигать» ------------------------------------------
CLIMB_TREES = stage(hill_climb, "climb_trees", kind="tree")
CLIMB_SHRUBS = stage(hill_climb, "climb_shrubs", kind="shrub")
experiment(Experiment("E22", "деревья -> подвигать деревья по индексу -> кустарники -> сдвиг",
                      stages=(place, GAP_SLACK, assort, quality, CLIMB_TREES, shrub_groups,
                              shrub_rows, HEDGES_TALL, UNDER, quality, refine),
                      overrides={"spacing_m": 5.0, **PRIORITY}))
experiment(Experiment("E23", "E21 + в конце подвигать кустарники по индексу",
                      stages=(place, GAP_SLACK, assort, shrub_groups, shrub_rows, HEDGES_TALL,
                              UNDER, quality, refine, CLIMB_SHRUBS),
                      overrides={"spacing_m": 5.0, **PRIORITY}))
experiment(Experiment("E24", "E21 + в конце подвигать деревья по индексу",
                      stages=(place, GAP_SLACK, assort, shrub_groups, shrub_rows, HEDGES_TALL,
                              UNDER, quality, refine, CLIMB_TREES),
                      overrides={"spacing_m": 5.0, **PRIORITY}))

# --- I. Разнообразие изгородей --------------------------------------------------------------
BEST = (place, GAP_SLACK, assort, shrub_groups, shrub_rows, HEDGES_TALL, UNDER, quality, refine)
BEST_OVERRIDES = {"spacing_m": 5.0, **PRIORITY}
experiment(Experiment("E25", "E21 + вид участка изгороди - самый редкий из допустимых",
                      stages=BEST, overrides={**BEST_OVERRIDES, "hedge_species_balance": True}))

# --- J. Мягкие квоты 10-20-30 ------------------------------------------------------------------
experiment(Experiment("E26", "сервис + мягкие квоты (штраф 5 за растение сверх доли)",
                      overrides={"quota_penalty": 5.0}))
experiment(Experiment("E27", "E21 + мягкие квоты (штраф 5)",
                      stages=BEST, overrides={**BEST_OVERRIDES, "quota_penalty": 5.0}))

# --- K. Победители, перенесённые в сервис (src), включены параметрами -----------------------
SERVICE_BEST = {
    "spacing_m": 5.0,
    "alley_priority": 2.0,
    "modes": ["alley", "lawn", "fill"],
    "curb_hedges": True,
    "curb_hedge_density_cap": False,  # предел В.1 для изгороди появился позже, см. E39
    "understory": True,
    **OLD,
}
experiment(Experiment("E28", "сервис с новыми этапами: шаг 5, надбавка аллее, добор зоны, "
                      "изгородь вдоль бортов 1 м, кустарник под кроной аллеи",
                      stages=SERVICE, overrides=SERVICE_BEST))
experiment(Experiment("E29", "E28 + ряд под аллеей шагом 1 м (743-ПП: высокие кустарники 0,5-1 м)",
                      stages=SERVICE, overrides={**SERVICE_BEST, "shrub_row_spacing_m": 1.0}))
experiment(Experiment("E30", "E28 + ряд под аллеей шагом 0,5 м",
                      stages=SERVICE, overrides={**SERVICE_BEST, "shrub_row_spacing_m": 0.5}))

# --- L. Абляция: что даёт каждый рычаг внутри E28 (убираем по одному) --------------------------
experiment(Experiment("E31", "E28 без шага 5 м (шаг 6 м)",
                      stages=SERVICE, overrides={**SERVICE_BEST, "spacing_m": 6.0}))
experiment(Experiment("E32", "E28 без надбавки аллее",
                      stages=SERVICE, overrides={**SERVICE_BEST, "alley_priority": 0.0}))
experiment(Experiment("E33", "E28 без добора зоны",
                      stages=SERVICE, overrides={**SERVICE_BEST, "modes": ["alley", "lawn"]}))
experiment(Experiment("E34", "E28 без изгороди вдоль бортов",
                      stages=SERVICE, overrides={**SERVICE_BEST, "curb_hedges": False}))
experiment(Experiment("E35", "E28 без кустарника под кроной",
                      stages=SERVICE, overrides={**SERVICE_BEST, "understory": False}))

# --- M. Квоты от выбора на месте, разнообразие изгородей ---------------------------------------
experiment(Experiment("E36", "E28 + вид участка изгороди - самый редкий из допустимых",
                      stages=SERVICE, overrides={**SERVICE_BEST, "hedge_species_balance": True}))
experiment(Experiment("E37", "E28 + квоты не строже 1/(медиана вариантов на месте)",
                      stages=SERVICE, overrides={**SERVICE_BEST, "quota_adaptive": True}))
experiment(Experiment("E38", "сервис + квоты от выбора на месте", overrides={"quota_adaptive": True}))

# --- N. Изгородь в пределах В.1 --------------------------------------------------------------
experiment(Experiment("E39", "E28 + изгородь не выше 720 кустарников на 1 км (МГСН В.1)",
                      stages=SERVICE, overrides={**SERVICE_BEST, "curb_hedge_density_cap": True}))
experiment(Experiment("E40", "E39 + вид участка изгороди - самый редкий",
                      stages=SERVICE, overrides={**SERVICE_BEST, "curb_hedge_density_cap": True,
                                                 "hedge_species_balance": True}))
experiment(Experiment("E41", "E40 без надбавки аллее",
                      stages=SERVICE, overrides={**SERVICE_BEST, "curb_hedge_density_cap": True,
                                                 "hedge_species_balance": True,
                                                 "alley_priority": 0.0}))

# --- O. Исключение «один экземпляр» от числа занятых мест ------------------------------------
experiment(Experiment("E42", "сервис + исключение «один экземпляр» до 300 мест (исправление)"))
FINAL = {**SERVICE_BEST, "curb_hedge_density_cap": True, "hedge_species_balance": True,
         "alley_priority": 0.0, "quota_single_places": 30.0}
experiment(Experiment("E43", "E41 + исправленное исключение «один экземпляр»",
                      stages=SERVICE, overrides=FINAL))

experiment(Experiment("E44", "E43 + надбавка аллее +2",
                      stages=SERVICE, overrides={**FINAL, "alley_priority": 2.0}))
experiment(Experiment("E45", "E42 + надбавка аллее +2",
                      overrides={"quota_single_places": 30.0, "alley_priority": 2.0}))

# --- P. Подбор знает о штрафах индекса ----------------------------------------------------------
FINAL2 = {**FINAL, "alley_priority": 2.0}
experiment(Experiment("E46", "E44 + подбор: вид с условием или слабый аллерген -0,2 к оценке",
                      stages=SERVICE, overrides={**FINAL2, "condition_penalty": 0.2}))
experiment(Experiment("E47", "E44 + то же, -0,5 к оценке",
                      stages=SERVICE, overrides={**FINAL2, "condition_penalty": 0.5}))

# --- Q. Изгородь: больше отступов от борта в полосе 2 м ------------------------------------------
FINAL3 = {**FINAL2, "condition_penalty": 0.2}
experiment(Experiment("E48", "E46 + отступы изгороди 1,3 / 1,0 / 1,6 / 1,9 м (вся полоса 2 м)",
                      stages=SERVICE,
                      overrides={**FINAL3, "shrub_row_curb_offsets_m": [1.3, 1.0, 1.6, 1.9]}))

# --- R. Кустарник там, где дереву нельзя, до нижней границы В.1 --------------------------------
SHRUB_FILL = stage(shrub_fill, "shrub_fill")
experiment(Experiment("E49", "E46 + группы кустарника у сетей, где дереву нельзя, до 600 на 1 км",
                      stages=(place, assort, shrub_groups, shrub_rows, understory_src, SHRUB_FILL,
                              quality, refine),
                      overrides=FINAL3))

experiment(Experiment("E50", "E46 + группы кустарника на газоне до 600 на 1 км (этап сервиса)",
                      stages=SERVICE, overrides={**FINAL3, "shrub_fill": True}))

# --- S. Абляция итога (E50): убираем по одному рычагу -----------------------------------------
FINAL4 = {**FINAL3, "shrub_fill": True}
ABLATIONS = {
    "E51": ("E50 без добора зоны", {"modes": ["alley", "lawn"]}),
    "E52": ("E50 без изгороди вдоль бортов", {"curb_hedges": False}),
    "E53": ("E50 без кустарника под кроной", {"understory": False}),
    "E54": ("E50 без групп кустарника на газоне", {"shrub_fill": False}),
    "E55": ("E50 с шагом 6 м", {"spacing_m": 6.0}),
    "E56": ("E50 без надбавки аллее", {"alley_priority": 0.0}),
    "E57": ("E50 без поправки на условия вида", {"condition_penalty": 0.0}),
    "E58": ("E50 без исправления исключения «один экземпляр»", {"quota_single_places": 1.0}),
    "E59": ("E50 без баланса видов изгороди", {"hedge_species_balance": False}),
}
for key, (title, change) in ABLATIONS.items():
    experiment(Experiment(key, title, stages=SERVICE, overrides={**FINAL4, **change}))

__all__ = ["BASE", "HEDGES", "HEDGES_HALF", "UNDER"]
