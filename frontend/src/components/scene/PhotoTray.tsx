/* Фото нейросетью на пульте 3D-вида: режим и ход заданий.
 *
 * Отправить кадр можно тремя путями: кнопкой «фото ИИ» на полосе (текущий вид), кнопкой
 * «в фото» у снимка и из галереи кадров. Все задания идут в одну очередь сервера, и здесь
 * видно каждое: место в очереди, полоса хода с оценкой по прошлым фото, готовый снимок. */

import { useEffect, useState } from 'react';

import type { PhotoOut } from '../../api/types';
import { expectedSeconds, photoProgress } from '../../lib/photos';

/** Сколько последних фото держит список: дальше - на странице галереи. */
const TRAY_MAX = 4;

export interface PhotoTrayProps {
  photos: PhotoOut[];
  available: boolean;
  reason: string | null;
  scenery: boolean;
  onScenery: (value: boolean) => void;
}

export function PhotoTray({ photos, available, reason, scenery, onScenery }: PhotoTrayProps) {
  const busy = photos.some((p) => p.state === 'queued' || p.state === 'running');
  const [now, setNow] = useState(() => Date.now());
  // Полоса хода двигается раз в секунду, пока модель работает.
  useEffect(() => {
    if (!busy) return;
    const timer = window.setInterval(() => {
      setNow(Date.now());
    }, 1000);
    return () => {
      window.clearInterval(timer);
    };
  }, [busy]);

  if (!available) {
    return (
      <div className="scene-field photo-tray">
        <span className="hud-label">Фото нейросетью</span>
        <p className="hint">Недоступно: {reason ?? 'генерация на сервере не настроена'}.</p>
      </div>
    );
  }
  const expected = expectedSeconds(photos);
  const recent = photos.slice(0, TRAY_MAX);
  return (
    <div className="scene-field photo-tray">
      <span className="hud-label">Фото нейросетью</span>
      <label className="check photo-mode">
        <input
          type="checkbox"
          checked={scenery}
          onChange={(e) => {
            onScenery(e.target.checked);
          }}
        />
        Дорисовать фон и деревья
      </label>
      {recent.length ? (
        <ul className="photo-list">
          {recent.map((photo) => {
            const progress = photoProgress(photo, photos, now, expected);
            const done = photo.state === 'succeeded' && photo.photo_url;
            return (
              <li key={photo.id} className="photo-item" data-state={photo.state}>
                <a
                  href={done ? (photo.photo_url ?? undefined) : photo.source_url}
                  target="_blank"
                  rel="noopener"
                  title={done ? 'Открыть фото целиком' : 'Кадр, который рисует модель'}
                >
                  <img
                    src={done ? (photo.raw_url ?? photo.source_url) : photo.source_url}
                    alt={photo.shot || 'Кадр для фото'}
                    width={96}
                    height={54}
                  />
                </a>
                <div className="photo-state">
                  <span className="photo-shot">{photo.shot || 'Кадр 3D-вида'}</span>
                  {photo.state === 'succeeded' ? null : (
                    <span
                      className="photo-bar"
                      role="progressbar"
                      aria-valuemin={0}
                      aria-valuemax={100}
                      aria-valuenow={Math.round(progress.share * 100)}
                      aria-label={progress.label}
                    >
                      <span style={{ width: `${String(progress.share * 100)}%` }} />
                    </span>
                  )}
                  <span className={photo.state === 'failed' ? 'photo-note bad' : 'photo-note'}>
                    {done ? (
                      <a href={photo.photo_url ?? undefined} target="_blank" rel="noopener">
                        готово{photo.scenery ? ', с фоном' : ''} ↗
                      </a>
                    ) : (
                      progress.label
                    )}
                  </span>
                </div>
              </li>
            );
          })}
        </ul>
      ) : (
        <p className="hint">
          Кнопка «фото ИИ» внизу отправит текущий вид, «в фото» у снимка - сам снимок.
        </p>
      )}
    </div>
  );
}
