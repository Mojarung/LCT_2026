"""Один черновик правок на все процессы сервиса: журнал правок рядом с прогоном.

При нескольких процессах (`--workers`, реплики в Kubernetes) у каждого свой кэш контекстов в
памяти. Правка, принятая одним процессом, пишется в журнал каталога прогона, и любой другой
процесс догоняет журнал, прежде чем отдать черновик, проверить точку или пересобрать DXF.
Каждый тест берёт свою копию каталога прогонов: журнал у тестов не общий.
"""

from __future__ import annotations

import pickle
import shutil
from dataclasses import replace
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient
from test_pipeline_synthetic import ROOT, _street

from green.application.editing import Edit, EditKind, RunContextCache
from green.application.errors import InputError
from green.bootstrap.container import build_container
from green.bootstrap.settings import Settings
from green.infrastructure.config.repositories import YamlSpeciesCatalog
from green.infrastructure.storage.contexts import CONTEXT, PickleRunContextStore, code_fingerprint
from green.infrastructure.storage.runs import FileSystemRunStore
from green.interfaces.api.app import API_PREFIX, create_app

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from pathlib import Path

    from green.application.editing import RunContext

SPECIES = YamlSpeciesCatalog(ROOT / "config" / "species.yaml")
# Точка на газоне синтетической улицы, куда можно добавить дерево (как в test_editing).
FREE_POINT = (100.0, 40.0)


@pytest.fixture(scope="module")
def pristine(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, str]:
    """Каталог прогонов с одним законченным прогоном; тесты правят его копии."""
    work = tmp_path_factory.mktemp("journal")
    source = work / "street.dxf"
    _street(source)
    settings = Settings(config_dir=ROOT / "config", runs_dir=work / "runs")
    with TestClient(create_app(build_container(settings))) as client:
        response = client.post(
            f"{API_PREFIX}/runs",
            files={"file": ("street.dxf", source.read_bytes(), "image/vnd.dxf")},
            data={"profile": "strict"},
        )
        run_id = str(response.json()["id"])
        assert client.get(f"{API_PREFIX}/runs/{run_id}").json()["state"] == "succeeded"
    return work / "runs", run_id


@pytest.fixture
def runs(pristine: tuple[Path, str], tmp_path: Path) -> Path:
    copy = tmp_path / "runs"
    shutil.copytree(pristine[0], copy)
    return copy


@pytest.fixture
def run_id(pristine: tuple[Path, str]) -> str:
    return pristine[1]


def _store(runs: Path) -> PickleRunContextStore:
    return PickleRunContextStore(FileSystemRunStore(runs), code_fingerprint())


def _process(runs: Path) -> RunContextCache:
    """Кэш контекстов отдельного процесса сервиса над общим каталогом прогонов."""
    return RunContextCache(SPECIES, store=_store(runs))


def _context(cache: RunContextCache, run_id: str) -> RunContext:
    context = cache.get(run_id)
    assert context is not None, "контекст прогона не поднялся"
    return context


def _layout(cache: RunContextCache, run_id: str) -> list[tuple[str, float, float]]:
    plan = _context(cache, run_id).plan
    return [(p.placement_id, p.x, p.y) for p in plan.placements]


def _total(cache: RunContextCache, run_id: str) -> int:
    plan = _context(cache, run_id).plan
    return len(plan.placements) + len(plan.rejections)


def _tree_code(cache: RunContextCache, run_id: str) -> str:
    plan = _context(cache, run_id).plan
    return next(p.species.code for p in plan.placements if p.species.is_tree)


def _add(cache: RunContextCache, run_id: str) -> Edit:
    x, y = FREE_POINT
    return Edit(EditKind.ADD, x=x, y=y, species_code=_tree_code(cache, run_id))


def test_edit_accepted_by_one_process_is_seen_by_another(runs: Path, run_id: str) -> None:
    """Второй процесс держал контекст в памяти до правки - и всё равно видит её."""
    first, second = _process(runs), _process(runs)
    before = _layout(second, run_id)
    moved, deleted = before[0][0], before[1][0]
    x, y = before[0][1] + 0.25, before[0][2] + 0.25

    first.edit(
        run_id,
        [Edit(EditKind.MOVE, placement_id=moved, x=x, y=y), Edit(EditKind.DELETE, deleted)],
    )

    seen = _layout(second, run_id)
    assert seen == _layout(first, run_id)
    assert len(seen) == len(before) - 1
    assert deleted not in {pid for pid, _, _ in seen}
    assert next((px, py) for pid, px, py in seen if pid == moved) == (x, y)


def test_rebuilt_context_is_not_edited_twice(runs: Path, run_id: str) -> None:
    """Контекст пересборки сохранён с номером последней правки: новый процесс применяет
    только правки после него. Добавление посадки заметно при повторе - посадок стало бы
    на одну больше."""
    first = _process(runs)
    total = _total(first, run_id)
    first.edit(run_id, [_add(first, run_id)])
    first.put(_context(first, run_id))  # так пересборка сохраняет контекст после записи DXF
    first.edit(
        run_id,
        [
            Edit(
                EditKind.ADD,
                x=FREE_POINT[0] + 6,
                y=FREE_POINT[1],
                species_code=_tree_code(first, run_id),
            )
        ],
    )

    fresh = _process(runs)

    assert _total(fresh, run_id) == total + 2
    assert _layout(fresh, run_id) == _layout(first, run_id)
    assert _context(fresh, run_id).applied_seq == _context(first, run_id).applied_seq == 2


def test_restarted_service_catches_up_with_the_journal(runs: Path, run_id: str) -> None:
    """Правка без пересборки: на диске контекст прогона, правка только в журнале."""
    first = _process(runs)
    victim = _layout(first, run_id)[0][0]
    first.edit(run_id, [Edit(EditKind.DELETE, victim)])

    restarted = _process(runs)

    assert _layout(restarted, run_id) == _layout(first, run_id)
    assert victim not in {pid for pid, _, _ in _layout(restarted, run_id)}


def test_rejected_edit_is_not_journaled(runs: Path, run_id: str) -> None:
    first = _process(runs)
    before = _layout(first, run_id)

    with pytest.raises(InputError, match="нет-такой"):
        first.edit(run_id, [Edit(EditKind.MOVE, placement_id="нет-такой", x=1.0, y=1.0)])

    assert _store(runs).edits_since(run_id, 0) == []
    assert _layout(_process(runs), run_id) == before
    assert _layout(first, run_id) == before


def test_edits_from_two_processes_are_applied_in_journal_order(runs: Path, run_id: str) -> None:
    """Оба процесса держат контекст; правят одну посадку по очереди - последней остаётся
    правка с большим номером журнала, у обоих."""
    first, second = _process(runs), _process(runs)
    layout = _layout(first, run_id)
    _layout(second, run_id)
    pid, x, y = layout[0]
    deleted = layout[1][0]

    first.edit(run_id, [Edit(EditKind.MOVE, placement_id=pid, x=x + 0.5, y=y)])
    second.edit(run_id, [Edit(EditKind.MOVE, placement_id=pid, x=x + 1.0, y=y)])
    first.edit(run_id, [Edit(EditKind.DELETE, deleted)])

    assert _layout(first, run_id) == _layout(second, run_id) == _layout(_process(runs), run_id)
    final = _layout(second, run_id)
    assert next((px, py) for p, px, py in final if p == pid) == (x + 1.0, y)
    assert deleted not in {p for p, _, _ in final}
    assert [seq for seq, _ in _store(runs).edits_since(run_id, 0)] == [1, 2, 3]


class _Interleaved(PickleRunContextStore):
    """Хранилище процесса, у которого перед первой дозаписью журнал успевает дописать другой
    процесс: окно между проверкой правки и записью, которое иначе ловится только нагрузкой."""

    def __init__(self, runs: Path, meanwhile: Callable[[], object]) -> None:
        super().__init__(FileSystemRunStore(runs), code_fingerprint())
        self._meanwhile: Callable[[], object] | None = meanwhile

    def append_edits(self, run_id: str, edits: Sequence[Edit], after: int) -> int | None:
        if self._meanwhile is not None:
            meanwhile, self._meanwhile = self._meanwhile, None
            meanwhile()
        return super().append_edits(run_id, edits, after)


def test_edit_overtaken_by_another_process_is_rechecked_on_the_new_plan(
    runs: Path, run_id: str
) -> None:
    """Обе правки удаляют разные посадки: вторая, опоздавшая к журналу, ложится после первой,
    и у обоих процессов пропали обе посадки."""
    second = _process(runs)
    layout = _layout(second, run_id)
    one, two = layout[0][0], layout[1][0]
    first = RunContextCache(
        SPECIES,
        store=_Interleaved(runs, lambda: second.edit(run_id, [Edit(EditKind.DELETE, one)])),
    )

    first.edit(run_id, [Edit(EditKind.DELETE, two)])

    assert [seq for seq, _ in _store(runs).edits_since(run_id, 0)] == [1, 2]
    assert _layout(first, run_id) == _layout(second, run_id) == _layout(_process(runs), run_id)
    assert {one, two}.isdisjoint(p for p, _, _ in _layout(first, run_id))


def test_edit_of_a_planting_just_deleted_elsewhere_is_refused(runs: Path, run_id: str) -> None:
    """Обе правки удаляют одну посадку: опоздавшая проверяется по плану, где посадки уже нет,
    отвергается и в журнал не попадает."""
    second = _process(runs)
    victim = _layout(second, run_id)[0][0]
    first = RunContextCache(
        SPECIES,
        store=_Interleaved(runs, lambda: second.edit(run_id, [Edit(EditKind.DELETE, victim)])),
    )

    with pytest.raises(InputError, match=victim):
        first.edit(run_id, [Edit(EditKind.DELETE, victim)])

    assert [seq for seq, _ in _store(runs).edits_since(run_id, 0)] == [1]
    assert _layout(first, run_id) == _layout(second, run_id)


def test_context_pickled_before_the_journal_reads_as_seq_zero(runs: Path, run_id: str) -> None:
    """Контекст из pickle без поля applied_seq (записан до журнала) поднимается с номером 0
    и догоняет журнал с начала."""
    first = _process(runs)
    old = replace(_context(first, run_id), _indexes={})
    del old.applied_seq  # так выглядит контекст, сохранённый до появления поля
    back = pickle.loads(pickle.dumps(old))  # noqa: S301 - свой объект, только что записан
    assert back.applied_seq == 0

    victim = _layout(first, run_id)[0][0]
    first.edit(run_id, [Edit(EditKind.DELETE, victim)])
    path = FileSystemRunStore(runs).state_file(run_id, CONTEXT)
    with path.open("wb") as handle:
        pickle.dump((code_fingerprint(), old), handle)

    restarted = _process(runs)

    assert _context(restarted, run_id).applied_seq == 1
    assert _layout(restarted, run_id) == _layout(first, run_id)


def test_deleted_run_does_not_resurface_from_another_process(runs: Path, run_id: str) -> None:
    """Прогон удалён через один процесс: другой, у которого контекст в памяти, больше его
    не отдаёт, и новый процесс тоже."""
    first, second = _process(runs), _process(runs)
    first.edit(run_id, [Edit(EditKind.DELETE, _layout(first, run_id)[0][0])])
    _layout(second, run_id)

    FileSystemRunStore(runs).delete(run_id)
    first.drop(run_id)

    assert second.get(run_id) is None
    assert _process(runs).get(run_id) is None
    assert not (runs / run_id).exists()


def test_two_services_share_one_draft_and_rebuild(runs: Path, run_id: str) -> None:
    """Два экземпляра сервиса над одним каталогом: правку принял один, черновик у обоих
    одинаковый, пересобирает другой - и в plan.json удалённой посадки нет."""
    settings = Settings(config_dir=ROOT / "config", runs_dir=runs)
    url = f"{API_PREFIX}/runs/{run_id}"
    with (
        TestClient(create_app(build_container(settings))) as one,
        TestClient(create_app(build_container(settings))) as two,
    ):
        draft = two.get(url + "/draft").json()["plan"]["placements"]
        tree = next(
            p
            for p in draft
            if p["planting_type"] == "tree" and SPECIES.get(p["species"]["code"]).is_conifer
        )
        edited = one.post(
            url + "/edits", json={"edits": [{"kind": "delete", "placement_id": tree["id"]}]}
        )
        assert edited.status_code == 200

        counts = {
            len(c.get(url + "/draft").json()["plan"]["placements"]) for c in (one, two, one, two)
        }
        assert counts == {len(draft) - 1}

        assert two.post(url + "/rebuild").status_code == 202
        status = one.get(url).json()
        assert status["state"] == "succeeded", status.get("error")
        saved = [p["id"] for p in one.get(url + "/artifacts/plan.json").json()["placements"]]
        assert tree["id"] not in saved
        assert len(saved) == len(draft) - 1
        assert one.get(url + "/draft").json()["stale"] is False
        assert two.get(url + "/draft").json()["stale"] is False
