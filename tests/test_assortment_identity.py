"""Opaque coordinate hashes must not choose the species at a physical location."""

import hashlib
from dataclasses import replace

import pytest
from test_assortment_pipeline import CATALOG, PARAMS, RULEBOOK, _plan

from green.application.assortment import assign_species


@pytest.mark.parametrize("solver", ["auto", "greedy"])
def test_translating_and_rekeying_places_preserves_species_and_public_ids(solver: str) -> None:
    original = _plan()
    dx, dy = 12345.125, -9876.375
    moved = replace(
        original,
        placements=tuple(
            replace(
                p,
                x=p.x + dx,
                y=p.y + dy,
                placement_id=hashlib.sha256(f"{p.x + dx}:{p.y + dy}".encode()).hexdigest()[:12],
            )
            for p in original.placements
        ),
    )
    params = replace(PARAMS, assortment_solver=solver)
    first = assign_species(original, RULEBOOK, CATALOG.all(), params)
    second = assign_species(moved, RULEBOOK, CATALOG.all(), params)
    assert first.placements
    assert {(p.x, p.y): p.species.code for p in first.placements} == {
        (p.x - dx, p.y - dy): p.species.code for p in second.placements
    }
    assert {p.placement_id for p in second.placements} <= {p.placement_id for p in moved.placements}
    assert {r.rejection_id for r in second.rejections} <= {p.placement_id for p in moved.placements}
