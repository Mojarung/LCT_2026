"""Веса индекса по методу анализа иерархий: собственный вектор, согласованность, сведение."""

from __future__ import annotations

import numpy as np
import pytest

from green.application.quality.weights import (
    GROUPS,
    aggregate,
    expert_weights,
    matrix,
    panel_weights,
    priorities,
)


def test_a_consistent_matrix_gives_exact_weights_and_zero_inconsistency() -> None:
    # Веса 0,5 / 0,25 / 0,25: a12 = 2, a13 = 2, a23 = 1 - матрица идеально согласована.
    result = priorities(matrix(3, [2, 2, 1]))
    assert result.weights == pytest.approx((0.5, 0.25, 0.25), abs=1e-6)
    assert result.cr == pytest.approx(0.0, abs=1e-6)
    assert result.consistent


def test_an_intransitive_judgement_fails_the_consistency_check() -> None:
    # A важнее B в 9 раз, B важнее C в 9 раз, но C важнее A в 9 раз - так не бывает.
    result = priorities(matrix(3, [9, 1 / 9, 9]))
    assert result.cr > 0.1
    assert not result.consistent


def test_judgements_outside_the_saaty_scale_are_rejected() -> None:
    with pytest.raises(ValueError, match="шкалы Саати"):
        matrix(3, [12, 1, 1])
    with pytest.raises(ValueError, match="нужно 6 суждений"):
        matrix(4, [1, 1, 1])


def test_identical_experts_aggregate_to_themselves() -> None:
    one = matrix(3, [3, 5, 2])
    assert np.allclose(aggregate([one, one, one]), one)


def test_term_weights_cover_every_term_and_sum_to_one() -> None:
    form = {
        "groups": [1, 1, 1, 1, 1, 1],
        "reliability": [1, 1, 1],
        "functions": [1, 1, 1],
        "composition": [1, 1, 1],
    }
    expert = expert_weights("равные", form)
    keys = {key for keys in GROUPS.values() for key in keys}
    assert set(expert.terms) == keys
    assert sum(expert.terms.values()) == pytest.approx(1.0, abs=1e-3)
    assert expert.terms["density"] == pytest.approx(0.25, abs=1e-3)


def test_the_panel_sits_between_experts_who_disagree() -> None:
    functions_first = {"groups": [1 / 3, 1, 1, 3, 3, 1], "reliability": [1, 1, 1]}
    reliability_first = {"groups": [3, 1, 1, 1 / 3, 1 / 3, 1], "reliability": [1, 1, 1]}
    for form in (functions_first, reliability_first):
        form.update({"functions": [1, 1, 1], "composition": [1, 1, 1]})
    panel = panel_weights({"a": functions_first, "b": reliability_first})
    a = expert_weights("a", functions_first).groups.weights
    b = expert_weights("b", reliability_first).groups.weights
    assert min(a[0], b[0]) < panel.groups.weights[0] < max(a[0], b[0])
