import { useId, useMemo, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router';

import { ApiError, artifactUrl, postJson } from '../api/client';
import { useArtifact, useRun } from '../api/queries';
import { type CenterRequest, type FitRequest, ReviewMap } from '../components/review/ReviewMap';
import { ReviewGroupTable } from '../components/review/ReviewGroupTable';
import { integer, plural } from '../lib/format';
import { geometryPath, joinPaths } from '../lib/reviewPaths';
import {
  ASSIGNABLE,
  type ClassificationJson,
  className,
  evidenceName,
  groupMembers,
  groupOrder,
  groupNeedsReview,
  relatedIndices,
  LABEL_ROLES,
  type ReviewGeometry,
  reviewJson,
  selectedIndices,
  selectedLabel,
  unresolvedCount,
} from '../lib/review';

const GEOMETRY = 'semantic-review.geojson';
const REPORT = 'classification.json';
const REVIEW_DXF = 'review-input.dxf';

/** Уточнение объектов по геометрии исходного CAD. Применение создаёт отдельный прогон;
 *  назначения привязаны к SHA-256 исходника, а не к его имени или показанной картинке. */
export function ReviewPage() {
  const { runId = '' } = useParams();
  const navigate = useNavigate();
  const ids = useId();
  const run = useRun(runId);
  const artifacts = run.data?.artifacts ?? [];
  const names = new Set(artifacts.map((a) => a.name));
  const loaded = Boolean(run.data);
  const geometry = useArtifact<ReviewGeometry>(runId, GEOMETRY, loaded && names.has(GEOMETRY));
  const reportName = names.has('review-classification.json')
    ? 'review-classification.json'
    : REPORT;
  const report = useArtifact<ClassificationJson>(
    runId,
    reportName,
    loaded && names.has(reportName),
  );

  const data = geometry.data;
  const classes = report.data;
  const mismatch = Boolean(data && classes && data.source_sha256 !== classes.source_sha256);
  // Один объект на пару артефактов: от него считаются пути карты, и пересобирать их на каждую
  // отрисовку страницы незачем.
  const ready = useMemo(
    () => (data && classes && !mismatch ? { data, classes } : null),
    [data, classes, mismatch],
  );

  const [search, setSearch] = useState('');
  const [onlyReview, setOnlyReview] = useState(false);
  const [applying, setApplying] = useState(false);
  const [applyError, setApplyError] = useState('');
  const order = useMemo(
    () =>
      classes
        ? groupOrder(classes).filter((i) => {
            const item = classes.groups[i];
            return (
              item &&
              (!onlyReview || groupNeedsReview(item)) &&
              `${item.layer} ${item.block ?? ''}`
                .toLocaleLowerCase()
                .includes(search.toLocaleLowerCase())
            );
          })
        : [],
    [classes, search, onlyReview],
  );
  const members = useMemo(
    () => (ready ? groupMembers(ready.data, ready.classes.groups.length) : []),
    [ready],
  );
  const paths = useMemo(
    () => (ready ? ready.data.features.map((f) => geometryPath(f.geometry)) : []),
    [ready],
  );
  const groupPaths = useMemo(
    () => members.map((indices) => joinPaths(paths, indices)),
    [members, paths],
  );

  const [group, setGroup] = useState<number | null>(null);
  const [objectValue, setObjectValue] = useState('0');
  const [kind, setKind] = useState('');
  const [assignments, setAssignments] = useState<Record<string, string>>({});
  const [labelsVisible, setLabelsVisible] = useState(false);
  const [labelValue, setLabelValue] = useState('0');
  const [labelRole, setLabelRole] = useState('ignore');
  const [labelAssignments, setLabelAssignments] = useState<Record<string, string>>({});
  const [showJson, setShowJson] = useState(false);
  const [fit, setFit] = useState<FitRequest | null>(null);
  const [center, setCenter] = useState<CenterRequest | null>(null);

  // Первой открывается первая группа списка - неизвестная, если такая есть.
  const currentGroup = group !== null && order.includes(group) ? group : (order[0] ?? 0);
  const inGroup = useMemo(() => members[currentGroup] ?? [], [members, currentGroup]);
  const chosen = useMemo(
    () =>
      ready && order.length
        ? relatedIndices(ready.data, selectedIndices(inGroup, objectValue))
        : [],
    [ready, order.length, inGroup, objectValue],
  );
  const label = ready ? selectedLabel(ready.data, labelValue) : null;
  const labels = ready?.data.labels ?? [];
  const manualCount = useMemo(() => {
    if (!ready) return 0;
    const refs = new Set(Object.keys(assignments));
    for (const feature of ready.data.features) {
      const method = ready.classes.groups[feature.properties.group]?.evidence.method ?? '';
      if (method.startsWith('explicit_') && ASSIGNABLE.includes(feature.properties.class))
        refs.add(feature.id);
    }
    return refs.size;
  }, [ready, assignments]);

  const fitTo = (indices: readonly number[]) => {
    setFit((previous) => ({ indices, token: (previous?.token ?? 0) + 1 }));
  };

  const selectGroup = (index: number) => {
    setGroup(index);
    setObjectValue('0');
    setKind('');
    fitTo(ready ? relatedIndices(ready.data, members[index] ?? []) : []);
  };
  const assignGroup = (index: number, value: string) => {
    if (!ready) return;
    selectGroup(index);
    const refs = relatedIndices(ready.data, members[index] ?? []).flatMap(
      (i) => ready.data.features[i]?.id ?? [],
    );
    setAssignments((previous) => {
      if (!value) {
        const drop = new Set(refs);
        return Object.fromEntries(Object.entries(previous).filter(([id]) => !drop.has(id)));
      }
      return { ...previous, ...Object.fromEntries(refs.map((ref) => [ref, value])) };
    });
  };
  const draftCount = Object.keys(assignments).length + Object.keys(labelAssignments).length;

  // Карта впервые показывает первую группу списка, как только данные пришли; дальше вид
  // меняют только запросы из полей и кнопок.
  const initialFit = useMemo<FitRequest | null>(
    () => (ready ? { indices: members[order[0] ?? 0] ?? [], token: 0 } : null),
    [ready, members, order],
  );

  // Нет прогона или нет геометрии - это не статус формы, а её отсутствие (nothing ниже).
  const status = (() => {
    if (mismatch) return 'Геометрия и отчёт относятся к разным исходникам.';
    if (geometry.isError) return geometry.error.message;
    if (report.isError) return report.error.message;
    if (!ready) return 'Читаем объекты…';
    const pending = unresolvedCount(ready.data, assignments, ready.classes);
    return `Элементов: ${integer(ready.data.features.length)}. Автоматически: ${integer(Math.max(0, ready.data.features.length - pending - manualCount))}. Не уточнено: ${integer(pending)}. Ваших назначений: ${integer(manualCount)}.`;
  })();

  const groupInfo = ready?.classes.groups[currentGroup];
  const evidence = groupInfo
    ? `${groupInfo.layer} / ${groupInfo.block ?? 'без блока'} / ${groupInfo.geometry}. Основание: ${evidenceName(groupInfo.evidence.method)}.`
    : 'Геометрических объектов нет.';

  const one = ready && chosen.length === 1 ? ready.data.features[chosen[0] ?? -1] : undefined;
  const detail = one
    ? [
        one.id,
        `Объект DXF: ${one.properties.source_entity_type ?? 'тип не сохранён'}`,
        `Класс: ${className(assignments[one.id] ?? one.properties.class)}`,
        `Границы, м: ${one.properties.bounds.join(', ')}`,
        `Погрешность геометрии, м: ${String(one.properties.error_m ?? 'нет данных')}`,
      ].join('\n')
    : `Выбрано объектов: ${integer(chosen.length)}. Класс назначается всем выбранным.`;

  const labelDetail = label
    ? [
        label.text,
        label.id,
        label.layer,
        (label.block_chain ?? []).join(' / '),
        `Роль: ${LABEL_ROLES[labelAssignments[label.id] ?? label.surface_role] ?? label.surface_role}. Основание: ${
          labelAssignments[label.id] ? 'назначено вами' : evidenceName(label.evidence?.method)
        }.`,
      ].join('\n')
    : `Подписей: ${integer(labels.length)}. На карте - номер и первые 80 символов, здесь - полный текст выбранной.`;

  const json =
    ready && run.data
      ? reviewJson(run.data.overrides, ready.data, ready.classes, assignments, labelAssignments)
      : '';

  const download = () => {
    const url = URL.createObjectURL(new Blob([json], { type: 'application/json' }));
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = 'input-review-overrides.json';
    anchor.click();
    window.setTimeout(() => {
      URL.revokeObjectURL(url);
    }, 1000);
  };

  const apply = async () => {
    if (!ready) return;
    setApplying(true);
    setApplyError('');
    try {
      const values = JSON.parse(json) as {
        feature_classes: Record<string, string>;
        label_roles: Record<string, string>;
      };
      const next = await postJson<{ id: string }>(
        `/api/v1/runs/${encodeURIComponent(runId)}/review`,
        {
          source_sha256: ready.data.source_sha256,
          feature_classes: values.feature_classes,
          label_roles: values.label_roles,
        },
      );
      await navigate(`/runs/${encodeURIComponent(next.id)}`);
    } catch (error) {
      setApplyError(error instanceof Error ? error.message : 'Не удалось запустить пересчёт');
    } finally {
      setApplying(false);
    }
  };

  const hasFeatures = Boolean(ready?.data.features.length);
  const canExport = hasFeatures || labels.length > 0;
  const runLink = `/runs/${encodeURIComponent(runId)}`;
  const missing = run.isError && run.error instanceof ApiError && run.error.status === 404;
  // Уточнять нечего: одна строка и дорога назад вместо формы из тринадцати отключённых полей
  // с нулями, которая спорила сама с собой (жюри дизайна, итерация 7).
  const nothing = run.isError
    ? missing
      ? 'Такого прогона нет.'
      : run.error.message
    : run.data && !names.has(GEOMETRY)
      ? 'Уточнять нечего: неизвестных объектов в этом прогоне сервис не сохранил.'
      : null;

  return (
    <div className="launch">
      <div className="sheet review-sheet">
        <header className="stamp">
          <div className="stamp-title">
            <h1>Уточнение объектов чертежа</h1>
            <p>{run.data?.source_name ?? runId}</p>
          </div>
          <p className="models-back">
            <Link to={missing ? '/' : runLink}>{missing ? '← все прогоны' : '← к прогону'}</Link>
          </p>
        </header>
        {nothing ? (
          // Дорога назад уже в шапке: вторая ссылка под той же строкой её повторяла.
          <div className="review-none" role="status">
            <p>{nothing}</p>
          </div>
        ) : (
          <div className="review-body">
            <div className="review-intro">
              <p className="hint">
                Тип меняется для всех объектов строки. Название слоя показывает их на карте. Новый
                тип сохранится как черновик до нажатия «Применить и пересчитать».
              </p>
              <p className="review-status" role="status">
                {status}
              </p>
            </div>
            <section className="review-controls" aria-label="Уточнение объектов">
              <div className="review-filters">
                <div className="field">
                  <label htmlFor={`${ids}-search`}>Поиск слоя или блока</label>
                  <input
                    type="text"
                    id={`${ids}-search`}
                    value={search}
                    onChange={(e) => {
                      setSearch(e.target.value);
                    }}
                  />
                </div>
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
              </div>
              {ready ? (
                <ReviewGroupTable
                  data={ready.data}
                  report={ready.classes}
                  order={order}
                  members={members}
                  assignments={assignments}
                  selected={currentGroup}
                  onSelect={selectGroup}
                  onAssign={assignGroup}
                />
              ) : null}
            </section>
            <section className="review-map" aria-label="Геометрия исходника">
              <h2>На чертеже: {order.length ? groupInfo?.layer : 'ничего не выбрано'}</h2>
              <p className="hint">
                Оранжевый — выбранная группа, красный — отдельный объект. Серый — остальной чертёж.
              </p>
              {ready ? (
                <ReviewMap
                  data={ready.data}
                  paths={paths}
                  groupPaths={groupPaths}
                  group={order.length ? currentGroup : -1}
                  selected={chosen}
                  objectChosen={Number(objectValue) > 0}
                  labelsVisible={labelsVisible}
                  label={label}
                  fit={fit ?? initialFit}
                  center={center}
                />
              ) : (
                <div className="review-empty">
                  {mismatch || geometry.isError || report.isError ? null : (
                    <span className="spinner" aria-hidden="true" />
                  )}
                </div>
              )}
              <details className="review-advanced">
                <summary>Отдельные объекты и основание распознавания</summary>
                <p className="hint">
                  {groupInfo?.layer}. Назначения в этом разделе действуют на выбранные объекты, а
                  список в таблице — на всю строку.
                </p>
                <p className="hint">{evidence}</p>
                {groupInfo?.review_reason ? (
                  <p className="hint">
                    {chosen.length > 0 &&
                    chosen.every((i) => assignments[ready?.data.features[i]?.id ?? ''])
                      ? 'Выбранные элементы уточнены. Примените назначения для пересчёта.'
                      : `Требует уточнения: ${groupInfo.review_reason}.`}
                  </p>
                ) : null}
                {ready?.data.callouts
                  ?.filter((c) =>
                    chosen.some((i) => c.source_refs.includes(ready.data.features[i]?.id ?? '')),
                  )
                  .map((c) => (
                    <p className="hint" key={c.label_ref}>
                      Выноска «{c.text}»: {c.reason}. Связанные штрихи выбираются вместе.
                    </p>
                  ))}

                <div className="field">
                  <label htmlFor={`${ids}-object`}>Объект в группе (0 - вся группа)</label>
                  <input
                    id={`${ids}-object`}
                    type="number"
                    min={0}
                    max={inGroup.length}
                    step={1}
                    value={objectValue}
                    disabled={!hasFeatures}
                    onChange={(event) => {
                      const value = event.target.value;
                      setObjectValue(value);
                      const next = selectedIndices(inGroup, value);
                      if (next.length) fitTo(next);
                    }}
                  />
                  {/* Моношрифт - только для данных объекта; фраза-подсказка - обычным текстом. */}
                  {one ? (
                    <pre className="review-detail">{detail}</pre>
                  ) : (
                    <p className="hint">{detail}</p>
                  )}
                </div>

                <div className="field">
                  <label htmlFor={`${ids}-class`}>Класс по исходнику</label>
                  <select
                    id={`${ids}-class`}
                    value={kind}
                    onChange={(event) => {
                      setKind(event.target.value);
                    }}
                  >
                    <option value="">Выберите класс</option>
                    {ASSIGNABLE.map((value) => (
                      <option key={value} value={value}>
                        {className(value)}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="review-actions">
                  <button
                    type="button"
                    className="ghost small"
                    disabled={
                      !chosen.length ||
                      chosen.some(
                        (i) =>
                          !ASSIGNABLE.includes(ready?.data.features[i]?.properties.class ?? ''),
                      )
                    }
                    onClick={() => {
                      if (!ready) return;
                      setAssignments((previous) => ({
                        ...previous,
                        ...Object.fromEntries(
                          chosen.map((i) => [
                            ready.data.features[i]?.id ?? '',
                            ready.data.features[i]?.properties.class ?? '',
                          ]),
                        ),
                      }));
                    }}
                  >
                    Подтвердить текущий класс
                  </button>
                  <button
                    type="button"
                    className="primary small"
                    disabled={!chosen.length || !kind}
                    onClick={() => {
                      if (!ready || !kind) return;
                      setAssignments((previous) => {
                        const next = { ...previous };
                        for (const index of chosen) {
                          const feature = ready.data.features[index];
                          if (feature) next[feature.id] = kind;
                        }
                        return next;
                      });
                    }}
                  >
                    Назначить класс ({integer(chosen.length)}{' '}
                    {plural(chosen.length, 'объект', 'объекта', 'объектов')})
                  </button>
                  <button
                    type="button"
                    className="ghost small"
                    disabled={!chosen.length}
                    onClick={() => {
                      if (!ready) return;
                      const drop = new Set(chosen.map((index) => ready.data.features[index]?.id));
                      setAssignments((previous) =>
                        Object.fromEntries(
                          Object.entries(previous).filter(([id]) => !drop.has(id)),
                        ),
                      );
                    }}
                  >
                    Отменить назначение
                  </button>
                </div>
              </details>
              <details className="review-advanced">
                <summary>Подписи и покрытия</summary>
                <label className="check">
                  <input
                    type="checkbox"
                    checked={labelsVisible}
                    onChange={(event) => {
                      setLabelsVisible(event.target.checked);
                    }}
                  />
                  Подписи на карте
                </label>

                <div className="field">
                  <label htmlFor={`${ids}-label`}>Номер подписи на карте (0 - не выбрана)</label>
                  <input
                    id={`${ids}-label`}
                    type="number"
                    min={0}
                    max={labels.length}
                    step={1}
                    value={labelValue}
                    disabled={!labels.length}
                    onChange={(event) => {
                      const value = event.target.value;
                      setLabelValue(value);
                      const next = ready ? selectedLabel(ready.data, value) : null;
                      if (next && Number.isFinite(next.x) && Number.isFinite(next.y)) {
                        setCenter((previous) => ({
                          x: next.x,
                          y: next.y,
                          token: (previous?.token ?? 0) + 1,
                        }));
                      }
                    }}
                  />
                  {label ? (
                    <pre className="review-detail">{labelDetail}</pre>
                  ) : (
                    <p className="hint">{labelDetail}</p>
                  )}
                </div>

                <div className="field">
                  <label htmlFor={`${ids}-role`}>Роль выбранной подписи</label>
                  <select
                    id={`${ids}-role`}
                    value={labelRole}
                    onChange={(event) => {
                      setLabelRole(event.target.value);
                    }}
                  >
                    <option value="ignore">Не использовать для покрытия</option>
                    <option value="soil">Обозначает грунт / газон</option>
                    <option value="paved">Обозначает твёрдое покрытие</option>
                  </select>
                </div>
                <div className="review-actions">
                  <button
                    type="button"
                    className="primary small"
                    disabled={!label}
                    onClick={() => {
                      if (!label) return;
                      setLabelAssignments((previous) => ({ ...previous, [label.id]: labelRole }));
                    }}
                  >
                    Назначить роль
                  </button>
                  <button
                    type="button"
                    className="ghost small"
                    disabled={!label}
                    onClick={() => {
                      if (!label) return;
                      setLabelAssignments((previous) =>
                        Object.fromEntries(
                          Object.entries(previous).filter(([id]) => id !== label.id),
                        ),
                      );
                    }}
                  >
                    Отменить роль
                  </button>
                </div>
              </details>
            </section>
            <details className="review-export review-advanced">
              <summary>Экспорт уточнений и исходника</summary>
              <div className="review-actions">
                <button
                  type="button"
                  className="ghost small"
                  disabled={!canExport}
                  aria-expanded={showJson}
                  aria-controls={`${ids}-json`}
                  onClick={() => {
                    setShowJson((v) => !v);
                  }}
                >
                  {showJson ? 'Скрыть JSON' : 'Показать JSON'}
                </button>
                <button
                  type="button"
                  className="primary small"
                  disabled={!canExport}
                  onClick={download}
                >
                  Скачать JSON
                </button>
              </div>
              {showJson ? (
                <div className="field">
                  <label htmlFor={`${ids}-json`}>JSON уточнений</label>
                  <textarea id={`${ids}-json`} readOnly rows={8} value={json} />
                </div>
              ) : null}

              {names.has(REVIEW_DXF) ? (
                <a href={artifactUrl(runId, REVIEW_DXF)} download>
                  Исходник для повторной проверки
                </a>
              ) : null}
            </details>
            <footer className="review-apply">
              <div>
                <strong>
                  {draftCount
                    ? `Назначений к применению: ${integer(draftCount)}`
                    : 'Новых назначений нет'}
                </strong>
                <p className="hint">
                  {draftCount
                    ? 'Пересчёт создаст новый прогон с вашими назначениями.'
                    : 'Измените тип в таблице или подтвердите сомнительное распознавание.'}{' '}
                  Исходный прогон сохранится.
                </p>
              </div>
              {names.has(REVIEW_DXF) ? (
                <button
                  type="button"
                  className="primary"
                  disabled={!canExport || applying || !draftCount}
                  onClick={() => void apply()}
                >
                  {applying ? 'Запускаем пересчёт…' : 'Применить и пересчитать'}
                </button>
              ) : (
                <p className="hint">
                  Для пересчёта нужна копия DXF. Скачайте JSON и запустите исходник с этими
                  уточнениями.
                </p>
              )}
              {applyError ? <p role="alert">{applyError}</p> : null}
            </footer>
          </div>
        )}
      </div>
    </div>
  );
}
