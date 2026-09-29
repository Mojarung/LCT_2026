/* Снимки и фото - отдельной панелью слева: всё, что снято, одним столбцом крупных карточек.
 *
 * Действия видны на самой карточке: открыть, скачать, отправить снимок в нейросеть. В шапке -
 * чем снимать: снимок кадра, снимок вдвое крупнее, фото нейросетью этого вида и режим фото.
 * Фото в работе видно по карточке: кадр, полоса хода и сколько осталось. */

import { type ReactNode, useEffect, useState } from 'react';

import type { PhotoOut } from '../../api/types';
import { mediaBadge, type MediaItem, mediaTitle, type Shot } from '../../lib/media';
import { BarButton } from './BarButton';
import { expectedSeconds, photoProgress } from '../../lib/photos';

export interface MediaPanelProps {
  items: MediaItem[];
  photos: PhotoOut[];
  available: boolean;
  reason: string | null;
  scenery: boolean;
  onScenery: (value: boolean) => void;
  modern: boolean;
  onModern: (value: boolean) => void;
  /** Редактор промпта фото нейросетью. */
  editor: ReactNode;
  shooting: boolean;
  sending: boolean;
  onShot: (scale: number) => void;
  onPhotoView: () => void;
  /** Сколько фото в очереди и в работе: значок крутится, пока модель рисует. */
  photoBusy: number;
  onShots: () => void;
  onRemoveShot: (id: number) => void;
  onDeletePhoto: (id: string) => void;
  onPhoto: (shot: Shot) => void;
  onOpen: (index: number) => void;
}

function thumbOf(item: MediaItem): string {
  if (item.kind === 'snapshot') return item.shot.url;
  const p = item.photo;
  return p.state === 'succeeded' ? (p.raw_url ?? p.source_url) : p.source_url;
}

export function MediaPanel({
  items,
  photos,
  available,
  reason,
  scenery,
  onScenery,
  modern,
  onModern,
  editor,
  shooting,
  sending,
  onShot,
  onPhotoView,
  photoBusy,
  onShots,
  onRemoveShot,
  onDeletePhoto,
  onPhoto,
  onOpen,
}: MediaPanelProps) {
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
    <section className="hud scene-media" aria-label="Снимки и фото">
      <header className="media-head">
        <h2>
          Снимки и фото <span className="media-count">{items.length}</span>
        </h2>
      </header>
      <div className="media-actions">
        <BarButton
          icon="snapshot"
          label="снимок"
          keyHint="P"
          disabled={shooting}
          title="Снимок кадра в PNG"
          onClick={() => {
            onShot(1);
          }}
        />
        <BarButton
          icon="snapshot"
          label="×2"
          disabled={shooting}
          title="Снимок вдвое крупнее по каждой стороне, для слайда"
          onClick={() => {
            onShot(2);
          }}
        />
        <BarButton
          icon={photoBusy ? 'spinner' : 'photo'}
          label={photoBusy ? `фото ИИ · ${String(photoBusy)}` : 'фото ИИ'}
          keyHint="F"
          accent
          spin={photoBusy > 0}
          disabled={!available || sending}
          title={
            available
              ? 'Фото нейросетью с этого вида, та же расстановка, около минуты'
              : `Фото недоступно: ${reason ?? 'не настроено'}`
          }
          onClick={onPhotoView}
        />
        <BarButton
          icon="shots"
          label="кадры"
          keyHint="K"
          title="Кадры улицы с автоматических ракурсов; K над растением - его кадры"
          onClick={onShots}
        />
      </div>
      {available ? (
        <label className="check media-mode">
          <input
            type="checkbox"
            checked={scenery}
            onChange={(e) => {
              onScenery(e.target.checked);
            }}
          />
          Фото ИИ: дорисовать фон и деревья, которых нет в плане
        </label>
      ) : null}
      {available ? (
        <label className="check media-mode">
          <input
            type="checkbox"
            checked={modern}
            onChange={(e) => {
              onModern(e.target.checked);
            }}
          />
          Современные московские фасады: объём и этажность те же
        </label>
      ) : null}
      {available ? (
        editor
      ) : (
        <p className="hint">Фото нейросетью недоступно: {reason ?? 'не настроено'}.</p>
      )}
      {items.length ? (
        <ul className="media-list">
          {items.map((item, index) => {
            const title = mediaTitle(item);
            const photo = item.kind === 'photo' ? item.photo : null;
            const pending = photo?.state === 'queued' || photo?.state === 'running';
            const progress = photo ? photoProgress(photo, photos, now, expected) : null;
            const state =
              item.kind === 'snapshot'
                ? `${String(item.shot.width)}×${String(item.shot.height)}`
                : photo?.state === 'succeeded'
                  ? `готово${photo.seconds ? ` за ${String(Math.round(photo.seconds))} с` : ''}`
                  : (progress?.label ?? '');
            const download =
              item.kind === 'snapshot'
                ? { href: item.shot.url, name: item.shot.name }
                : photo?.photo_url
                  ? { href: photo.photo_url, name: `${photo.id}.jpg` }
                  : null;
            return (
              <li key={item.key} className="media-card" data-pending={pending || undefined}>
                <button
                  type="button"
                  className="media-open"
                  title="Открыть крупно"
                  onClick={() => {
                    onOpen(index);
                  }}
                >
                  <img src={thumbOf(item)} alt={title} width={272} height={153} />
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
                <p className="media-info">
                  <strong>{title}</strong>
                  <span className={photo?.state === 'failed' ? 'bad' : undefined}>{state}</span>
                </p>
                <div className="media-card-actions">
                  <button
                    type="button"
                    className="ghost small"
                    onClick={() => {
                      onOpen(index);
                    }}
                  >
                    открыть
                  </button>
                  {download ? (
                    <a className="ghost small button" href={download.href} download={download.name}>
                      скачать
                    </a>
                  ) : null}
                  <button
                    type="button"
                    className="ghost small media-delete"
                    disabled={pending}
                    title={pending ? 'Фото ещё рисуется' : 'Удалить'}
                    onClick={() => {
                      if (item.kind === 'snapshot') onRemoveShot(item.shot.id);
                      else onDeletePhoto(item.photo.id);
                    }}
                  >
                    удалить
                  </button>
                  {item.kind === 'snapshot' && available ? (
                    <button
                      type="button"
                      className="ghost small"
                      onClick={() => {
                        onPhoto(item.shot);
                      }}
                    >
                      в фото ИИ
                    </button>
                  ) : null}
                </div>
              </li>
            );
          })}
        </ul>
      ) : (
        <p className="hint media-empty">
          Здесь соберутся снимки и фото нейросетью. Скачивание - только по кнопке.
        </p>
      )}
    </section>
  );
}
