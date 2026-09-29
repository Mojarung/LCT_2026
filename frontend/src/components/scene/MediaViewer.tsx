/* Просмотр снимков и фото на странице: большой кадр, листание, сравнение с 3D-кадром.
 *
 * Модальный <dialog>: над шапкой сайта, фокус внутри, Esc закрывает. Стрелки листают всю
 * галерею. У фото нейросетью переключатель «фото / 3D-кадр» показывает, по какому кадру его
 * нарисовали: расстановку можно сверить глазами. Скачивание - только по кнопке. */

import { useEffect, useRef, useState } from 'react';

import type { PhotoOut } from '../../api/types';
import { mediaBadge, type MediaItem, mediaTitle, type Shot } from '../../lib/media';
import { expectedSeconds, photoProgress } from '../../lib/photos';

export interface MediaViewerProps {
  items: MediaItem[];
  index: number;
  photos: PhotoOut[];
  onIndex: (index: number) => void;
  onClose: () => void;
  /** Отправить снимок в нейросеть; нет - фото недоступно. */
  onPhoto?: (shot: Shot) => void;
}

type Side = 'photo' | 'frame';

function photoMeta(p: PhotoOut): string {
  const mode = p.scenery ? 'с фоном и деревьями' : 'по плану';
  const size = p.upscaled
    ? `${String(p.width * 4)}×${String(p.height * 4)}`
    : `${String(p.width)}×${String(p.height)}`;
  const time = p.seconds ? `, ${String(Math.round(p.seconds))} с` : '';
  return `Фото нейросетью ${mode}, ${size}${time}`;
}

export function MediaViewer({ items, index, photos, onIndex, onClose, onPhoto }: MediaViewerProps) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [side, setSide] = useState<Side>('photo');
  const [now, setNow] = useState(() => Date.now());
  // Пока открыт просмотр, строка хода фото в работе пересчитывается раз в секунду.
  useEffect(() => {
    const timer = window.setInterval(() => {
      setNow(Date.now());
    }, 1000);
    return () => {
      window.clearInterval(timer);
    };
  }, []);
  const item = items[index];
  const close = useRef(onClose);
  useEffect(() => {
    close.current = onClose;
  });
  const go = useRef((step: number) => {
    onIndex(step);
  });
  useEffect(() => {
    go.current = (step: number) => {
      if (!items.length) return;
      onIndex((index + step + items.length) % items.length);
    };
  });

  useEffect(() => {
    const box = dialog.current;
    if (!box) return;
    if (typeof box.showModal === 'function' && !box.open) box.showModal();
    const cancel = (event: Event) => {
      event.preventDefault();
      close.current();
    };
    const key = (event: KeyboardEvent) => {
      if (event.key === 'ArrowRight') go.current(1);
      else if (event.key === 'ArrowLeft') go.current(-1);
      else return;
      event.preventDefault();
    };
    box.addEventListener('cancel', cancel);
    box.addEventListener('keydown', key);
    return () => {
      box.removeEventListener('cancel', cancel);
      box.removeEventListener('keydown', key);
      if (box.open) box.close();
    };
  }, []);

  if (!item) return null;
  const title = mediaTitle(item);
  let image: string;
  let meta: string;
  let download: { href: string; name: string } | null = null;
  let original: string | null = null;
  let status: string | null = null;
  if (item.kind === 'snapshot') {
    image = item.shot.url;
    meta = `Снимок 3D-вида, ${String(item.shot.width)}×${String(item.shot.height)}`;
    download = { href: item.shot.url, name: item.shot.name };
  } else {
    const p = item.photo;
    const done = p.state === 'succeeded' && p.photo_url;
    const showPhoto = done && side === 'photo';
    image = showPhoto ? (p.photo_url ?? p.source_url) : p.source_url;
    meta = done ? photoMeta(p) : 'Кадр, который рисует модель';
    if (done) {
      download = { href: p.photo_url ?? '', name: `${p.id}.jpg` };
      original = p.photo_url;
    }
    if (!done) status = photoProgress(p, photos, now, expectedSeconds(photos)).label;
  }

  return (
    <dialog ref={dialog} className="media-viewer" aria-label={title}>
      <header className="viewer-head">
        <div>
          <h2>{title}</h2>
          <p className="viewer-meta">
            <span className="media-badge">{mediaBadge(item)}</span> {meta}
          </p>
        </div>
        <span className="viewer-count">
          {index + 1} / {items.length}
        </span>
        <button type="button" className="ghost small" onClick={onClose}>
          закрыть · Esc
        </button>
      </header>
      <div className="viewer-stage">
        <button
          type="button"
          className="viewer-nav prev"
          aria-label="Предыдущий"
          disabled={items.length < 2}
          onClick={() => {
            go.current(-1);
          }}
        >
          ‹
        </button>
        <img src={image} alt={title} />
        {status ? (
          <p className="viewer-status" role="status">
            {status}
          </p>
        ) : null}
        <button
          type="button"
          className="viewer-nav next"
          aria-label="Следующий"
          disabled={items.length < 2}
          onClick={() => {
            go.current(1);
          }}
        >
          ›
        </button>
      </div>
      <footer className="viewer-foot">
        {item.kind === 'photo' && item.photo.state === 'succeeded' ? (
          <div className="segmented viewer-sides" role="radiogroup" aria-label="Что показать">
            {(
              [
                ['photo', 'фото'],
                ['frame', '3D-кадр'],
              ] as const
            ).map(([value, label]) => (
              <button
                key={value}
                type="button"
                role="radio"
                aria-checked={side === value}
                onClick={() => {
                  setSide(value);
                }}
              >
                {label}
              </button>
            ))}
          </div>
        ) : null}
        <div className="viewer-actions">
          {item.kind === 'snapshot' && onPhoto ? (
            <button
              type="button"
              className="primary small"
              onClick={() => {
                onPhoto(item.shot);
              }}
            >
              в фото ИИ
            </button>
          ) : null}
          {download ? (
            <a className="ghost small button" href={download.href} download={download.name}>
              скачать
            </a>
          ) : null}
          {original ? (
            <a className="ghost small button" href={original} target="_blank" rel="noopener">
              оригинал ↗
            </a>
          ) : null}
        </div>
      </footer>
    </dialog>
  );
}
