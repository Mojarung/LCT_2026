import { useId, useMemo, useState } from 'react';
import { Link, useParams } from 'react-router';

import { ApiError, artifactUrl } from '../api/client';
import { useArtifact, useRun } from '../api/queries';
import { type CenterRequest, type FitRequest, ReviewMap } from '../components/review/ReviewMap';
import { integer, plural } from '../lib/format';
import { profileTitle } from '../lib/profiles';
import { geometryPath, joinPaths } from '../lib/reviewPaths';
import {
  ASSIGNABLE,
  type ClassificationJson,
  className,
  evidenceName,
  groupMembers,
  groupOrder,
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

/** Подпись группы в списке: слой, тип геометрии, число объектов и класс. */
function groupText(group: ClassificationJson['groups'][number]): string {
  const count = `${integer(group.features)} ${plural(group.features, 'объект', 'объекта', 'объектов')}`;
  return `${group.layer}, ${group.geometry}, ${count}: ${className(group.object_class)}`;
}

/** Уточнение объектов чертежа. Перенос страницы тиммейта (static/review.js): человек смотрит
 *  неизвестные группы на самой геометрии исходника, назначает класс по легенде и роль
 *  подписям, а сервис получает это только JSON-ом повторного прогона. Здесь ничего не
 *  сохраняется на сервере и ничего не доказывается о полноте съёмки или грунте. */
export function ReviewPage() {
  const { runId = '' } = useParams();
  const ids = useId();
  const run = useRun(runId);
  const artifacts = run.data?.artifacts ?? [];
  const names = new Set(artifacts.map((a) => a.name));
  const loaded = Boolean(run.data);
  const geometry = useArtifact<ReviewGeometry>(runId, GEOMETRY, loaded && names.has(GEOMETRY));
  const report = useArtifact<ClassificationJson>(runId, REPORT, loaded && names.has(REPORT));

  const data = geometry.data;
  const classes = report.data;
  const mismatch = Boolean(data && classes && data.source_sha256 !== classes.source_sha256);
  // Один объект на пару артефактов: от него считаются пути карты, и пересобирать их на каждую
  // отрисовку страницы незачем.
  const ready = useMemo(
    () => (data && classes && !mismatch ? { data, classes } : null),
    [data, classes, mismatch],
  );

  const order = useMemo(() => (classes ? groupOrder(classes) : []), [classes]);
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
  const [labelsVisible, setLabelsVisible] = useState(true);
  const [labelValue, setLabelValue] = useState('0');
  const [labelRole, setLabelRole] = useState('ignore');
  const [labelAssignments, setLabelAssignments] = useState<Record<string, string>>({});
  const [showJson, setShowJson] = useState(false);
  const [fit, setFit] = useState<FitRequest | null>(null);
  const [center, setCenter] = useState<CenterRequest | null>(null);

  // Первой открывается первая группа списка - неизвестная, если такая есть.
  const currentGroup = group ?? order[0] ?? 0;
  const inGroup = useMemo(() => members[currentGroup] ?? [], [members, currentGroup]);
  const chosen = useMemo(() => selectedIndices(inGroup, objectValue), [inGroup, objectValue]);
  const label = ready ? selectedLabel(ready.data, labelValue) : null;
  const labels = ready?.data.labels ?? [];

  const fitTo = (indices: readonly number[]) => {
    setFit((previous) => ({ indices, token: (previous?.token ?? 0) + 1 }));
  };

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
    return `Объектов: ${integer(ready.data.features.length)}. Не уточнено: ${integer(
      unresolvedCount(ready.data, assignments),
    )}. Ваших назначений: ${integer(Object.keys(assignments).length)}.`;
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
            <section className="review-controls" aria-label="Уточнение объектов">
              <p className="hint">
                Выберите группу, осмотрите объекты на карте и назначьте класс по исходнику и
                легенде. Уточнение классов не подтверждает полноту съёмки и пригодность грунта.
              </p>
              <p className="review-status" role="status">
                {status}
              </p>

              <div className="field">
                <label htmlFor={`${ids}-group`}>Группа</label>
                <select
                  id={`${ids}-group`}
                  value={currentGroup}
                  disabled={!hasFeatures}
                  onChange={(event) => {
                    const next = Number(event.target.value);
                    setGroup(next);
                    setObjectValue('0');
                    fitTo(members[next] ?? []);
                  }}
                >
                  {ready
                    ? order.map((index) => {
                        const item = ready.classes.groups[index];
                        return item ? (
                          <option key={index} value={index}>
                            {groupText(item)}
                          </option>
                        ) : null;
                      })
                    : null}
                </select>
                <p className="hint">{evidence}</p>
              </div>

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
                      Object.fromEntries(Object.entries(previous).filter(([id]) => !drop.has(id))),
                    );
                  }}
                >
                  Отменить назначение
                </button>
              </div>

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
                <p className="hint">
                  Затем загрузите{' '}
                  <a href={artifactUrl(runId, REVIEW_DXF)} download>
                    этот DXF
                  </a>{' '}
                  новым прогоном с тем же профилем «{run.data ? profileTitle(run.data.profile) : ''}
                  » и вставьте JSON в поле «Параметры поверх профиля, JSON». Остальные файлы
                  комплекта уже собраны в этом DXF.
                </p>
              ) : run.data && names.has(GEOMETRY) ? (
                <p className="hint">
                  Копию DXF сохранить не удалось. Для повторного прогона нужен исходник с хешем из
                  отчёта, изменённый файл придётся уточнять заново.
                </p>
              ) : null}
              <p className="hint">
                Оранжевый - выбранная группа, красный - выбранный объект, серый - остальной чертёж.
                Координаты местные, в метрах. Формы не упрощены, неизвестные объекты не скрыты.
              </p>
            </section>

            <section className="review-map" aria-label="Геометрия исходника">
              {ready ? (
                <ReviewMap
                  data={ready.data}
                  paths={paths}
                  groupPaths={groupPaths}
                  group={currentGroup}
                  selected={chosen}
                  objectChosen={Number(objectValue) > 0}
                  labelsVisible={labelsVisible}
                  label={label}
                  fit={fit ?? initialFit}
                  center={center}
                />
              ) : (
                <div className="review-empty">
                  {/* Пока объекты читаются - знак загрузки; при ошибке он не крутится вечно:
                    причину называет строка статуса слева. */}
                  {mismatch || geometry.isError || report.isError ? null : (
                    <span className="spinner" aria-hidden="true" />
                  )}
                </div>
              )}
            </section>
          </div>
        )}
      </div>
    </div>
  );
}
