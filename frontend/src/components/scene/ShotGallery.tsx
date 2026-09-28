/* Галерея автоматических кадров 3D-вида и фото по ним.
 *
 * Открывается поверх сцены: по ссылке с карты (?plant=<id>, ?shots=street) - сразу, до
 * свободного полёта, или кнопкой «кадры». Кадр можно открыть в 3D с того же места или
 * отправить модели на фото. По умолчанию модель держит только то, что есть в кадре; галочка
 * разрешает ей дорисовать город у горизонта и деревья на пустых газонах - это уже не план. */

import { useEffect, useId, useRef } from 'react';

import type { PhotoOut } from '../../api/types';
import type { AutoShot } from '../../scene3d/autoshots';

export interface GalleryShot extends AutoShot {
  url: string;
  blob: Blob;
}

const STATE_RU: Record<PhotoOut['state'], string> = {
  queued: 'в очереди',
  running: 'модель рисует, около 1,5 мин',
  succeeded: 'готово',
  failed: 'не удалось',
};

/** Сколько прежних фото прогона показывать: дальше - одинаковые кадры одного облёта. */
const EARLIER_MAX = 6;

function PhotoStatus({ photo, label }: { photo: PhotoOut; label: string }) {
  if (photo.state === 'succeeded' && photo.photo_url) {
    const scale = photo.upscaled ? 4 : 1;
    return (
      <figure className="gallery-photo">
        <a href={photo.photo_url} target="_blank" rel="noopener">
          <img
            src={photo.raw_url ?? photo.photo_url}
            alt={`Фото: ${label}`}
            width={320}
            height={180}
          />
        </a>
        <figcaption>
          {photo.scenery ? 'с фоном и деревьями' : 'по плану'} ·{' '}
          <a href={photo.photo_url} target="_blank" rel="noopener">
            {photo.width * scale}×{photo.height * scale} ↗
          </a>
        </figcaption>
      </figure>
    );
  }
  return (
    <p className={photo.state === 'failed' ? 'notice' : 'hint'} role="status">
      {STATE_RU[photo.state]}
      {photo.error ? `: ${photo.error}` : ''}
    </p>
  );
}

export interface ShotGalleryProps {
  title: string;
  shots: GalleryShot[];
  busy: boolean;
  error: string | null;
  /** Фото прогона с сервера, новые сверху. */
  photos: PhotoOut[];
  /** Какое фото заказано по какому кадру в этой вкладке. */
  requested: Record<string, string>;
  available: boolean;
  reason: string | null;
  scenery: boolean;
  onScenery: (value: boolean) => void;
  onPhoto: (shot: GalleryShot) => void;
  onOpen: (shot: GalleryShot) => void;
  /** Переход к кадрам улицы: только у галереи одной посадки. */
  onStreet?: () => void;
  onClose: () => void;
}

export function ShotGallery({
  title,
  shots,
  busy,
  error,
  photos,
  requested,
  available,
  reason,
  scenery,
  onScenery,
  onPhoto,
  onOpen,
  onStreet,
  onClose,
}: ShotGalleryProps) {
  const byId = new Map(photos.map((p) => [p.id, p]));
  const ordered = new Set(Object.values(requested));
  const earlier = photos
    .filter((p) => !ordered.has(p.id) && p.state === 'succeeded')
    .slice(0, EARLIER_MAX);
  const heading = useRef<HTMLHeadingElement>(null);
  const headingId = useId();
  // Диалог: фокус на заголовок, иначе он остаётся на body за галереей.
  useEffect(() => {
    heading.current?.focus();
  }, []);
  return (
    <section
      className="hud scene-gallery"
      role="dialog"
      aria-modal="true"
      aria-labelledby={headingId}
    >
      <header className="gallery-head">
        <h2 id={headingId} ref={heading} tabIndex={-1}>
          {title}
        </h2>
        <div className="gallery-tools">
          {onStreet ? (
            <button type="button" className="ghost small" onClick={onStreet} disabled={busy}>
              кадры улицы
            </button>
          ) : null}
          <button type="button" className="ghost small" onClick={onClose}>
            к 3D-виду · Esc
          </button>
        </div>
      </header>
      {available ? (
        <div className="gallery-scenery">
          <label>
            <input
              type="checkbox"
              checked={scenery}
              aria-describedby="gallery-scenery-note"
              onChange={(e) => {
                onScenery(e.target.checked);
              }}
            />
            Дорисовать фон и деревья
          </label>
          <p className="hint" id="gallery-scenery-note">
            Модель добавит город у горизонта и деревья, которых нет в плане.
          </p>
        </div>
      ) : (
        <p className="hint">Фото недоступно: {reason ?? 'генерация на сервере не настроена'}.</p>
      )}
      {error ? <p className="notice">{error}</p> : null}
      {busy && !shots.length ? <p role="status">Снимаю кадры…</p> : null}
      <ul className="gallery-grid">
        {shots.map((shot) => {
          const photo = requested[shot.key] ? byId.get(requested[shot.key] ?? '') : undefined;
          return (
            <li key={shot.key} className="gallery-card">
              <div className="gallery-frame">
                <img src={shot.url} alt={`${title}. ${shot.label}`} width={320} height={180} />
                {shot.mark ? (
                  <span
                    className="gallery-mark"
                    aria-hidden="true"
                    style={{ left: `${shot.mark.u * 100}%`, top: `${shot.mark.v * 100}%` }}
                  />
                ) : null}
              </div>
              <p className="gallery-label">{shot.label}</p>
              {shot.names.length ? (
                <p
                  className="hint gallery-species"
                  title={[...shot.trees, ...shot.shrubs].join(', ')}
                >
                  {shot.names.slice(0, 5).join(', ')}
                </p>
              ) : null}
              <div className="gallery-actions">
                <button
                  type="button"
                  className="ghost small"
                  title="Свободный полёт с этого ракурса"
                  onClick={() => {
                    onOpen(shot);
                  }}
                >
                  в 3D
                </button>
                <a
                  className="ghost small button"
                  href={shot.url}
                  download={`${shot.key}.png`}
                  title="Скачать кадр"
                >
                  PNG
                </a>
                {available ? (
                  <button
                    type="button"
                    className="primary small"
                    disabled={photo?.state === 'queued' || photo?.state === 'running'}
                    title="Фото по кадру от Qwen-Image-2.1, расстановка та же"
                    onClick={() => {
                      onPhoto(shot);
                    }}
                  >
                    {photo ? 'ещё фото' : 'фото'}
                  </button>
                ) : null}
              </div>
              {photo ? <PhotoStatus photo={photo} label={shot.label} /> : null}
            </li>
          );
        })}
      </ul>
      {earlier.length ? (
        <>
          <h3 className="gallery-sub">Прежние фото прогона</h3>
          <ul className="gallery-grid">
            {earlier.map((photo) => (
              <li key={photo.id} className="gallery-card">
                <PhotoStatus photo={photo} label="прежнее фото прогона" />
              </li>
            ))}
          </ul>
        </>
      ) : null}
    </section>
  );
}
