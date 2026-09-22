"""A blocked near offset must not hide another valid offset at the same station."""

from green.application.constraints import ConstraintIndex
from green.application.params import PlanParams
from green.application.placement import MODE_ALLEY, _Candidate, _offer, _Selector
from green.domain.planting import Species


def test_spacing_conflict_tries_the_next_offset() -> None:
    selector = _Selector(Species("test", "Тест", "Test test", 3), PlanParams())
    index = ConstraintIndex([], [], require_utility_data=False)
    _offer(
        index,
        selector,
        [
            _Candidate(0, MODE_ALLEY, 0, 0),
            _Candidate(1, MODE_ALLEY, 5, 0),
            _Candidate(1, MODE_ALLEY, 6, 0),
        ],
    )
    assert [(p.x, p.y) for p in selector.placements] == [(0, 0), (6, 0)]
