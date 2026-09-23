import type { ArtifactOut } from '../../api/types';
import { humanSize } from '../../lib/format';

/** Файлы, ради которых прогон и запускали. Что внутри - говорит сам интерфейс, коротко. */
const HEADLINE: { name: string; label: string; what: string }[] = [
  {
    name: 'result.dxf',
    label: 'Скачать DXF',
    what: 'план посадок на слоях GREEN_*, исходные слои целы',
  },
  {
    name: 'interpretations.csv',
    label: 'Интерпретации, CSV',
    what: 'по строке на проверенную норму: посадка, правило, акт, пункт',
  },
];

/** Выгрузка - конец работы, поэтому она прибита к низу панели результата и не уезжает в
 *  прокрутку вместе со списком видов. Служебные файлы свёрнуты. */
export function Downloads({ artifacts }: { artifacts: readonly ArtifactOut[] }) {
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
      {headline.map((file, index) => {
        const artifact = byName.get(file.name);
        return (
          <a
            key={file.name}
            className={`dl ${index === 0 ? 'primary' : 'ghost'}`}
            href={artifact?.url}
            download
          >
            <span>{file.label}</span>
            <span className="size">{size(artifact)}</span>
          </a>
        );
      })}
      {headline.length ? (
        <p className="dl-note">{headline.map((file) => file.what).join('. ')}.</p>
      ) : null}
      {service.length ? (
        <details className="fold">
          <summary>Файлы прогона: {service.length}</summary>
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
    </div>
  );
}
