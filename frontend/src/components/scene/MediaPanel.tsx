/* Снимки и фото - отдельной панелью слева: всё, что снято, одним столбцом крупных карточек.
 *
 * Действия видны на самой карточке: открыть, скачать, удалить, отправить снимок в нейросеть.
 * В шапке - три способа снять (снимок, фото нейросетью, кадры улицы), под ними настройки
 * каждого переключателями: снимок крупнее, фон и деревья, новые фасады, промпт в своём окне.
 * Фото в работе видно по карточке: кадр, полоса хода и сколько осталось. */

import { type ReactNode, useEffect, useState } from 'react';

import type { PhotoOut } from '../../api/types';
import { mediaBadge, type MediaItem, mediaTitle, type Shot } from '../../lib/media';
import { SceneIcon } from '../icons';
import { BarButton } from './BarButton';
import { SideToggle } from './SideToggle';
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
  /** Промпт поправлен руками: кнопка «промпт» это показывает. */
  customPrompt: boolean;
  onPrompt: () => void;
  /** Свёрнута ли панель к левому краю. */
  collapsed: boolean;
  onToggle: () => void;
  /** Во сколько раз снимок крупнее экрана: 1 или 2, общий для кнопки и клавиши P. */
  shotScale: number;
  onShotScale: (scale: number) => void;
  shooting: boolean;
  sending: boolean;
  onShot: () => void;
  onPhotoView: () => void;
  /** Сколько фото в очереди и в работе: значок крутится, пока модель рисует. */
  photoBusy: number;
  onShots: () => void;
  onRemoveShot: (id: number) => void;
  onDeletePhoto: (id: string) => void;
  onPhoto: (shot: Shot) => void;
  onOpen: (index: number) => void;
}

function Chip({
  pressed,
  title,
  onClick,
  children,
}: {
  pressed: boolean;
  title: string;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button type="button" className="chip" aria-pressed={pressed} title={title} onClick={onClick}>
      {children}
    </button>
  );
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
  customPrompt,
  onPrompt,
  collapsed,
  onToggle,
  shotScale,
  onShotScale,
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
    <section
      className={collapsed ? 'hud scene-media collapsed' : 'hud scene-media'}
      aria-label="Снимки и фото"
    >
      <SideToggle
        side="left"
        collapsed={collapsed}
        label="снимки и фото"
        icon="snapshot"
        count={items.length}
        onToggle={onToggle}
      />
      <header className="media-head">
        <h2>
          Снимки и фото <span className="media-count">{items.length}</span>
        </h2>
      </header>
      <div className="media-actions">
        <BarButton
          icon="snapshot"
          label={shotScale > 1 ? 'снимок ×2' : 'снимок'}
          keyHint="P"
          disabled={shooting}
          title={shotScale > 1 ? 'Снимок кадра в PNG, вдвое крупнее' : 'Снимок кадра в PNG'}
          onClick={onShot}
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
      <dl className="media-options">
        <div className="media-option-row">
          <dt>снимок</dt>
          <dd>
            <Chip
              pressed={shotScale > 1}
              title="Снимок вдвое крупнее по каждой стороне, для слайда"
              onClick={() => {
                onShotScale(shotScale > 1 ? 1 : 2);
              }}
            >
              крупнее ×2
            </Chip>
          </dd>
        </div>
        {available ? (
          <div>
            <dt>
              фото ИИ
              <button
                type="button"
                className="chip chip-prompt"
                data-custom={customPrompt || undefined}
                title="Открыть промпт: что нарисовать и чего не рисовать"
                onClick={onPrompt}
              >
                <SceneIcon name="prompt" />
                {customPrompt ? 'свой промпт' : 'промпт'}
              </button>
            </dt>
            <dd>
              <Chip
                pressed={scenery}
                title="Дорисовать фон и деревья, которых нет в плане"
                onClick={() => {
                  onScenery(!scenery);
                }}
              >
                фон и деревья
              </Chip>
              <Chip
                pressed={modern}
                title="Современные московские фасады: объём и этажность те же"
                onClick={() => {
                  onModern(!modern);
                }}
              >
                новые фасады
              </Chip>
            </dd>
          </div>
        ) : null}
      </dl>
      {available ? null : (
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
