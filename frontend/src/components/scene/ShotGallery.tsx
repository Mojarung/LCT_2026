/* Галерея автоматических кадров 3D-вида и фото по ним.
 *
 * Открывается поверх сцены: по ссылке с карты (?plant=<id>, ?shots=street) - сразу, до
 * свободного полёта, или кнопкой «кадры». Кадр можно открыть в 3D с того же места или
 * отправить модели на фото. По умолчанию модель держит только то, что есть в кадре; галочка
 * разрешает ей дорисовать город у горизонта и деревья на пустых газонах - это уже не план. */

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

function PhotoStatus({ photo }: { photo: PhotoOut }) {
  if (photo.state === 'succeeded' && photo.photo_url) {
    return (
      <a className="gallery-photo" href={photo.photo_url} target="_blank" rel="noopener">
        <img src={photo.raw_url ?? photo.photo_url} alt="Фото по кадру" width={320} height={180} />
        <span>
          фото{photo.scenery ? ' с фоном и деревьями' : ''}
          {photo.seconds ? `, ${Math.round(photo.seconds)} с` : ''} · открыть{' '}
          {photo.upscaled ? `${photo.width * 4}×${photo.height * 4}` : ''}
        </span>
      </a>
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
  onStreet: () => void;
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
  const earlier = photos.filter((p) => !ordered.has(p.id) && p.state === 'succeeded');
  return (
    <section className="hud scene-gallery" aria-label="Кадры и фото участка">
      <header className="gallery-head">
        <div>
          <h2>{title}</h2>
          <p className="hint">
            Ракурсы подобраны автоматически: объект виден целиком, солнце за спиной.
          </p>
        </div>
        <div className="gallery-tools">
          <button type="button" className="ghost small" onClick={onStreet} disabled={busy}>
            кадры всей улицы
          </button>
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
              <img src={shot.url} alt={shot.label} width={320} height={180} />
              <p className="gallery-label">{shot.label}</p>
              {shot.trees.length || shot.shrubs.length ? (
                <p className="hint gallery-species">
                  {[...shot.trees.slice(0, 3), ...shot.shrubs.slice(0, 3)].join(', ')}
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
                    className="small"
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
              {photo ? <PhotoStatus photo={photo} /> : null}
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
                <PhotoStatus photo={photo} />
              </li>
            ))}
          </ul>
        </>
      ) : null}
    </section>
  );
}
