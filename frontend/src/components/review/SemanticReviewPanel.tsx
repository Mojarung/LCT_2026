import { useEffect, useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router';

import { postJson } from '../../api/client';
import { useArtifact } from '../../api/queries';
import type { RunOut } from '../../api/types';
import { integer } from '../../lib/format';
import {
  boundsOf,
  className,
  groupMembers,
  groupNeedsReview,
  groupOrder,
  relatedIndices,
  reviewJson,
  unresolvedCount,
  type ClassificationJson,
  type ReviewGeometry,
} from '../../lib/review';
import { useEngine } from '../../state/engine';
import { ReviewGroupTable } from './ReviewGroupTable';

/** Уточнение на том же плане: закрытие прячет подсветку, но сохраняет черновик. */
export function SemanticReviewPanel({
  run,
  open,
  onClose,
}: {
  run: RunOut;
  open: boolean;
  onClose: () => void;
}) {
  const engine = useEngine();
  const navigate = useNavigate();
  const names = new Set((run.artifacts ?? []).map((a) => a.name));
  const geometry = useArtifact<ReviewGeometry>(run.id, 'semantic-review.geojson', open);
  const report = useArtifact<ClassificationJson>(
    run.id,
    names.has('review-classification.json') ? 'review-classification.json' : 'classification.json',
    open,
  );
  const [search, setSearch] = useState('');
  const [onlyReview, setOnlyReview] = useState(false);
  const [showDecoration, setShowDecoration] = useState(false);
  const [selected, setSelected] = useState<number | null>(null);
  const [objectAt, setObjectAt] = useState<number | null>(null);
  const [canRestoreView, setCanRestoreView] = useState(false);
  const [assignments, setAssignments] = useState<Record<string, string>>({});
  const [applying, setApplying] = useState(false);
  const [error, setError] = useState('');
  const data = geometry.data;
  const classes = report.data;
  const mismatch = data && classes && data.source_sha256 !== classes.source_sha256;
  const ready = data && classes && !mismatch;
  const members = useMemo(
    () => (data && classes ? groupMembers(data, classes.groups.length) : []),
    [data, classes],
  );
  const order = useMemo(
    () =>
      classes
        ? groupOrder(classes).filter((i) => {
            const item = classes.groups[i];
            return (
              item &&
              (!onlyReview || groupNeedsReview(item)) &&
              (showDecoration || item.object_class !== 'ignore' || groupNeedsReview(item)) &&
              `${item.layer} ${item.block ?? ''}`
                .toLocaleLowerCase()
                .includes(search.toLocaleLowerCase())
            );
          })
        : [],
    [classes, onlyReview, showDecoration, search],
  );
  // Пока человек не выбрал строку, весь план остаётся обзором, без случайного слоя «0».
  const current = selected !== null && order.includes(selected) ? selected : -1;
  const chosen = useMemo(() => {
    if (!ready || current < 0) return [];
    const groupMembers = members[current] ?? [];
    const one = objectAt === null ? undefined : groupMembers[objectAt];
    return relatedIndices(data, objectAt === null ? groupMembers : one === undefined ? [] : [one]);
  }, [ready, data, members, current, objectAt]);
  const selectedGeometry = useMemo(
    () => (data ? chosen.flatMap((i) => data.features[i]?.geometry ?? []) : []),
    [data, chosen],
  );
  const changedGeometry = useMemo(
    () => (data ? data.features.filter((f) => assignments[f.id]).map((f) => f.geometry) : []),
    [data, assignments],
  );
  useEffect(() => {
    const currentEngine = engine.current;
    currentEngine?.setSemanticReview(
      open && ready ? { selected: selectedGeometry, changed: changedGeometry } : null,
    );
  }, [engine, open, ready, selectedGeometry, changedGeometry]);
  useEffect(() => {
    const currentEngine = engine.current;
    return () => {
      currentEngine?.setSemanticReview(null);
    };
  }, [engine]);
  useEffect(() => {
    if (!open) return;
    const close = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', close);
    return () => {
      window.removeEventListener('keydown', close);
    };
  }, [open, onClose]);
  const focus = (indices: number[], automatic = false) => {
    if (!ready || !indices.length) return;
    const moved = engine.current?.focusSemanticReview(boundsOf(data, indices), automatic);
    if (moved) setCanRestoreView(true);
  };
  const selectGroup = (index: number) => {
    if (!ready) return;
    setSelected(index);
    setObjectAt(null);
    focus(relatedIndices(data, members[index] ?? []), true);
  };
  const stepObject = (delta: number) => {
    const list = members[current] ?? [];
    if (!ready || !list.length) return;
    const next =
      objectAt === null
        ? delta > 0
          ? 0
          : list.length - 1
        : (objectAt + delta + list.length) % list.length;
    const index = list[next];
    if (index === undefined) return;
    setObjectAt(next);
    focus(relatedIndices(data, [index]));
  };
  const assign = (index: number, value: string) => {
    if (!ready) return;
    setSelected(index);
    setObjectAt(null);
    const refs = new Set(
      relatedIndices(data, members[index] ?? []).flatMap((i) => data.features[i]?.id ?? []),
    );
    setAssignments((previous) =>
      value
        ? { ...previous, ...Object.fromEntries([...refs].map((id) => [id, value])) }
        : Object.fromEntries(Object.entries(previous).filter(([id]) => !refs.has(id))),
    );
  };
  const count = Object.keys(assignments).length;
  const selectedGroup = classes?.groups[current];
  const selectedTypes = data
    ? [
        ...new Set(
          chosen.flatMap((i) => {
            const f = data.features[i];
            return f ? [assignments[f.id] ?? f.properties.class] : [];
          }),
        ),
      ]
        .map(className)
        .join(', ')
    : '';
  const apply = async () => {
    if (!ready || !count) return;
    setApplying(true);
    setError('');
    try {
      const values = JSON.parse(reviewJson(run.overrides, data, classes, assignments, {})) as {
        feature_classes: Record<string, string>;
        label_roles: Record<string, string>;
      };
      const next = await postJson<{ id: string }>(
        `/api/v1/runs/${encodeURIComponent(run.id)}/review`,
        {
          source_sha256: data.source_sha256,
          feature_classes: values.feature_classes,
          label_roles: values.label_roles,
        },
      );
      await navigate(`/runs/${encodeURIComponent(next.id)}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Не удалось запустить пересчёт');
    } finally {
      setApplying(false);
    }
  };
  return (
    <>
      {open && ready ? (
        <div className="semantic-map-key" role="status" data-map-obstacle="top">
          <strong>
            {selectedGroup
              ? `${selectedGroup.layer} · ${integer(chosen.length)} шт.`
              : 'Выберите слой в таблице'}
          </strong>
          <span>
            {selectedGroup
              ? selectedTypes
              : 'Подсветка появится на этом плане. При необходимости карта приблизит выбранные объекты.'}
          </span>
          <span>
            <i className="semantic-key-selected" />
            Выбрано <i className="semantic-key-changed" />
            Новое назначение
          </span>
        </div>
      ) : null}
      <section
        id="semantic-review-panel"
        className="hud semantic-review-panel"
        hidden={!open}
        data-map-obstacle="side"
        role="dialog"
        aria-modal="false"
        aria-label="Типы объектов чертежа"
      >
        <header>
          <h2>Объекты чертежа</h2>
          <button
            type="button"
            className="ghost small"
            onClick={onClose}
            aria-label="Свернуть уточнение объектов"
          >
            Свернуть ×
          </button>
        </header>
        <p className="hint">
          Выбор строки подсвечивает и показывает объекты на плане. Новый тип действует на всю строку
          после пересчёта.
        </p>
        {!ready ? (
          <p role={geometry.isError || report.isError || mismatch ? 'alert' : 'status'}>
            {mismatch
              ? 'Геометрия и отчёт относятся к разным исходникам.'
              : (geometry.error?.message ?? report.error?.message ?? 'Читаем объекты…')}
          </p>
        ) : (
          <>
            <p className="semantic-summary">
              Элементов DXF: {integer(data.features.length)} · требуют уточнения:{' '}
              {integer(unresolvedCount(data, assignments, classes))}
            </p>
            <div className="review-filters">
              <label className="field">
                Поиск слоя или блока
                <input
                  type="text"
                  value={search}
                  onChange={(e) => {
                    setSearch(e.target.value);
                  }}
                />
              </label>
              <label className="check">
                <input
                  type="checkbox"
                  checked={onlyReview}
                  onChange={(e) => {
                    setOnlyReview(e.target.checked);
                  }}
                />
                Только требующие уточнения
              </label>
              <label className="check">
                <input
                  type="checkbox"
                  checked={showDecoration}
                  onChange={(event) => {
                    setShowDecoration(event.target.checked);
                  }}
                />
                Показывать оформление
              </label>
            </div>
            <div className="semantic-selection">
              <span>
                {selectedGroup
                  ? `${selectedGroup.layer} · ${integer(chosen.length)} шт.`
                  : 'Слой не выбран'}
              </span>
              <button
                type="button"
                className="ghost small"
                disabled={!chosen.length}
                onClick={() => {
                  focus(chosen);
                }}
              >
                Приблизить выбранное
              </button>
            </div>
            <div className="semantic-object-nav">
              <button
                type="button"
                className="ghost small"
                aria-label="Предыдущий объект группы"
                disabled={current < 0 || !members[current]?.length}
                onClick={() => {
                  stepObject(-1);
                }}
              >
                ←
              </button>
              <span>
                {current < 0
                  ? 'Выберите строку'
                  : objectAt === null
                    ? `Вся группа · ${integer(members[current]?.length ?? 0)} шт.`
                    : `Объект ${integer(objectAt + 1)} из ${integer(members[current]?.length ?? 0)}`}
              </span>
              <button
                type="button"
                className="ghost small"
                aria-label="Следующий объект группы"
                disabled={current < 0 || !members[current]?.length}
                onClick={() => {
                  stepObject(1);
                }}
              >
                →
              </button>
              {objectAt !== null ? (
                <button
                  type="button"
                  className="ghost small"
                  onClick={() => {
                    setObjectAt(null);
                    focus(relatedIndices(data, members[current] ?? []));
                  }}
                >
                  Вся группа
                </button>
              ) : null}
              {canRestoreView ? (
                <button
                  type="button"
                  className="ghost small"
                  onClick={() => {
                    engine.current?.restoreSemanticReviewView();
                    setCanRestoreView(false);
                  }}
                >
                  Вернуться к предыдущему виду
                </button>
              ) : null}
            </div>
            {objectAt !== null ? (
              <p className="hint semantic-scope">
                Показан один объект. Новый тип в таблице назначается всей группе.
              </p>
            ) : null}
            <ReviewGroupTable
              data={data}
              report={classes}
              order={order}
              members={members}
              assignments={assignments}
              selected={current}
              onSelect={selectGroup}
              onAssign={assign}
            />
          </>
        )}
        <footer>
          <p role="status">
            {count ? `Назначений к применению: ${integer(count)}` : 'Новых назначений нет'}
          </p>
          <button
            type="button"
            className="primary"
            disabled={!ready || !count || applying || !names.has('review-input.dxf')}
            onClick={() => {
              void apply();
            }}
          >
            {applying ? 'Запускаем пересчёт…' : 'Применить и пересчитать'}
          </button>
          {error ? <p role="alert">{error}</p> : null}
          <Link to={`/runs/${encodeURIComponent(run.id)}/review`}>
            Отдельные объекты, подписи и экспорт
          </Link>
          <p className="hint">
            Черновик сохраняется при сворачивании. Пересчёт создаёт новый прогон.
          </p>
        </footer>
      </section>
    </>
  );
}
