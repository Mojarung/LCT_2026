import type { ArtifactOut } from '../../api/types';
import { humanSize } from '../../lib/format';

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
];

/** Выгрузка - конец работы, поэтому она прибита к низу панели результата и не уезжает в
 *  прокрутку вместе со списком видов. Главные файлы - одной строкой, служебные свёрнуты. */
export function Downloads({
  artifacts,
  notes = [],
}: {
  artifacts: readonly ArtifactOut[];
  /** Журнал чтения чертежа и склейки комплекта (summary.load_notes): рядом с файлами, а не
   *  в сводке плана - это про исходник, а не про посадки. */
  notes?: readonly string[];
}) {
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
          <span>
            Скачать план <span className="download-format">DXF</span>
          </span>
          <span className="size">{size(byName.get('result.dxf'))}</span>
        </a>
      ) : null}
      {headline.some((file) => file.name !== 'result.dxf') || service.length ? (
        <details className="fold download-more">
          <summary>Отчёты и другие файлы</summary>
          <ul className="artifact-list">
            {headline
              .filter((file) => file.name !== 'result.dxf')
              .map((file) => (
                <li key={file.name}>
                  <a
                    href={byName.get(file.name)?.url}
                    title={file.what}
                    {...(file.open ? { target: '_blank', rel: 'noopener' } : { download: true })}
                  >
                    <span>{file.label}</span>
                    <span className="size">{size(byName.get(file.name))}</span>
                  </a>
                </li>
              ))}
          </ul>
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
        </details>
      ) : null}
      {notes.length ? (
        <details className="fold">
          <summary>Чтение чертежа: {notes.length}</summary>
          <ul className="warn-list">
            {notes.map((text) => (
              <li key={text}>{text}</li>
            ))}
          </ul>
        </details>
      ) : null}
    </div>
  );
}
