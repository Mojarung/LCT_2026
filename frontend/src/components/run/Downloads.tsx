import { useState } from 'react';

import type { ArtifactOut } from '../../api/types';
import { Link } from 'react-router';
import { humanSize } from '../../lib/format';
import { UiIcon } from '../icons';
import { Modal, SheetButton } from '../ui/Modal';

/** Файлы, ради которых прогон и запускали. Что внутри - в подсказке у кнопки: абзац под
 *  кнопками съедал строки списка видов на высоте проектора. */
const HEADLINE: { name: string; label: string; what: string; open?: boolean }[] = [
  {
    name: 'result.dxf',
    label: 'Скачать DXF',
    what: 'План посадок на слоях GREEN_*, исходные слои целы',
  },
  {
    name: 'interpretations.csv',
    label: 'Нормы · CSV',
    what: 'По строке на проверенную норму: посадка, правило, акт, пункт',
  },
  {
    name: 'report.html',
    label: 'Отчёт по посадкам',
    what: 'По каждой посадке определяющая норма, запас и пункт акта; печатается в PDF',
    open: true,
  },
  {
    name: 'note.docx',
    label: 'Пояснительная записка · DOCX',
    what: 'Участок, нормативная база, решения, баланс «было - стало» и ведомость по форме 9',
  },
  {
    name: 'classification.json',
    label: 'Распознавание объектов · JSON',
    what: 'Как сервис отнёс объекты чертежа к классам: распознано, выведено по имени, не опознано',
  },
];

/** Выгрузка - конец работы, поэтому она прибита к низу панели результата и не уезжает в
 *  прокрутку вместе со списком видов. Главные файлы - одной строкой, служебные свёрнуты. */
export function Downloads({
  runId,
  artifacts,
  notes = [],
  onReview,
}: {
  runId: string;
  artifacts: readonly ArtifactOut[];
  /** Журнал чтения чертежа и склейки комплекта (summary.load_notes): рядом с файлами, а не
   *  в сводке плана - это про исходник, а не про посадки. */
  notes?: readonly string[];
  onReview?: () => void;
}) {
  const [open, setOpen] = useState(false);
  const byName = new Map(artifacts.map((artifact) => [artifact.name, artifact]));
  const headline = HEADLINE.filter((file) => byName.has(file.name));
  const service = artifacts.filter(
    (artifact) => !HEADLINE.some((file) => file.name === artifact.name),
  );
  if (!headline.length && !service.length) return null;
  const size = (artifact: ArtifactOut | undefined) =>
    artifact?.size_bytes == null ? '' : humanSize(artifact.size_bytes);
  return (
    <div className="hud-foot downloads">
      {byName.has('result.dxf') ? (
        <a className="dl primary download-plan" href={byName.get('result.dxf')?.url} download>
          <UiIcon name="download" />
          <span className="dl-label">
            Скачать план <span className="download-format">DXF</span>
          </span>
          <span className="size">{size(byName.get('result.dxf'))}</span>
        </a>
      ) : null}
      {headline.some((file) => file.name !== 'result.dxf') || service.length || notes.length ? (
        <SheetButton
          icon="files"
          label="Отчёты и другие файлы"
          onClick={() => {
            setOpen(true);
          }}
        />
      ) : null}
      {/* Отчёты, служебные файлы и журнал чтения - в окне по центру: в узкой панели раскрытый
          список из пятнадцати файлов выдавливал сводку. */}
      <Modal
        open={open}
        title="Отчёты и файлы прогона"
        onClose={() => {
          setOpen(false);
        }}
      >
        {headline.some((file) => file.name !== 'result.dxf') ||
        byName.has('semantic-review.geojson') ? (
          <ul className="artifact-list artifact-main">
            {byName.has('semantic-review.geojson') ? (
              <li>
                {onReview ? (
                  <button
                    type="button"
                    className="review-download-link"
                    onClick={() => {
                      setOpen(false);
                      onReview();
                    }}
                  >
                    Проверить распознавание объектов
                  </button>
                ) : (
                  <Link to={`/runs/${encodeURIComponent(runId)}/review`}>
                    Проверить распознавание объектов
                  </Link>
                )}
              </li>
            ) : null}
            {headline
              .filter((file) => file.name !== 'result.dxf')
              .map((file) => (
                <li key={file.name}>
                  <a
                    href={byName.get(file.name)?.url}
                    {...(file.open ? { target: '_blank', rel: 'noopener' } : { download: true })}
                  >
                    <span className="artifact-name">
                      <b>{file.label}</b>
                      <span>{file.what}</span>
                    </span>
                    <span className="size">{size(byName.get(file.name))}</span>
                  </a>
                </li>
              ))}
          </ul>
        ) : null}
        {service.length ? (
          <details className="fold">
            <summary>Файлы расчёта · {service.length}</summary>
            <ul className="artifact-list">
              {service.map((artifact) => (
                <li key={artifact.name}>
                  <a href={artifact.url} download>
                    <span>{artifact.name}</span>
                    <span className="size">{size(artifact)}</span>
                  </a>
                </li>
              ))}
            </ul>
          </details>
        ) : null}
        {notes.length ? (
          <details className="fold">
            <summary>Чтение чертежа · {notes.length}</summary>
            <ul className="warn-list">
              {notes.map((text) => (
                <li key={text}>{text}</li>
              ))}
            </ul>
          </details>
        ) : null}
      </Modal>
    </div>
  );
}
