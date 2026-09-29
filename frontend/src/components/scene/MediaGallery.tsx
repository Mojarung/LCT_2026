/* Общая галерея на пульте: превью снимков и фото нейросетью одной сеткой.
 *
 * Щелчок открывает просмотр на странице (MediaViewer), скачивание - только оттуда, по кнопке.
 * Фото в работе видно сразу: превью - кадр, который рисует модель, поверх полоса хода. */

import { useEffect, useState } from 'react';

import type { PhotoOut } from '../../api/types';
import { mediaBadge, type MediaItem, mediaTitle } from '../../lib/media';
import { expectedSeconds, photoProgress } from '../../lib/photos';

export interface MediaGalleryProps {
  items: MediaItem[];
  photos: PhotoOut[];
  available: boolean;
  reason: string | null;
  scenery: boolean;
  onScenery: (value: boolean) => void;
  onOpen: (index: number) => void;
}

function thumbOf(item: MediaItem): string {
  if (item.kind === 'snapshot') return item.shot.url;
  const p = item.photo;
  return p.state === 'succeeded' ? (p.raw_url ?? p.source_url) : p.source_url;
}

export function MediaGallery({
  items,
  photos,
  available,
  reason,
  scenery,
  onScenery,
  onOpen,
}: MediaGalleryProps) {
  const busy = photos.some((p) => p.state === 'queued' || p.state === 'running');
  const [now, setNow] = useState(() => Date.now());
  // Полосы хода двигаются раз в секунду, пока модель работает.
  useEffect(() => {
    if (!busy) return;
    const timer = window.setInterval(() => {
      setNow(Date.now());
    }, 1000);
    return () => {
      window.clearInterval(timer);
    };
  }, [busy]);
  const expected = expectedSeconds(photos);

  return (
    <div className="media">
      {items.length ? (
        <ul className="media-grid">
          {items.map((item, index) => {
            const pending =
              item.kind === 'photo' &&
              (item.photo.state === 'queued' || item.photo.state === 'running');
            const progress =
              item.kind === 'photo' ? photoProgress(item.photo, photos, now, expected) : null;
            const title = mediaTitle(item);
            return (
              <li key={item.key}>
                <button
                  type="button"
                  className="media-thumb"
                  data-kind={item.kind}
                  data-pending={pending ? 'true' : undefined}
                  title={progress && item.kind === 'photo' ? `${title}: ${progress.label}` : title}
                  onClick={() => {
                    onOpen(index);
                  }}
                >
                  <img src={thumbOf(item)} alt={title} width={96} height={54} />
                  <span
                    className="media-badge"
                    data-bad={mediaBadge(item) === 'ошибка' || undefined}
                  >
                    {mediaBadge(item)}
                  </span>
                  {pending && progress ? (
                    <span className="media-progress" aria-hidden="true">
                      <span style={{ width: `${String(progress.share * 100)}%` }} />
                    </span>
                  ) : null}
                </button>
              </li>
            );
          })}
        </ul>
      ) : (
        <p className="hint">
          Здесь соберутся снимки и фото нейросетью. Щелчок по превью открывает просмотр.
        </p>
      )}
      {available ? (
        <label className="check photo-mode">
          <input
            type="checkbox"
            checked={scenery}
            onChange={(e) => {
              onScenery(e.target.checked);
            }}
          />
          Фото ИИ: дорисовать фон и деревья
        </label>
      ) : (
        <p className="hint">Фото нейросетью недоступно: {reason ?? 'не настроено на сервере'}.</p>
      )}
    </div>
  );
}
