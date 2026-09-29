/* Общая галерея 3D-вида: снимки этой вкладки и фото нейросетью с сервера в одном списке.
 *
 * Снимки живут в памяти страницы (скачать - по кнопке), фото - на сервере и переживают
 * перезагрузку. Порядок один: новое сверху, чтобы только что сделанное было первым. */

import type { PhotoOut } from '../api/types';

export interface Shot {
  /** Время снимка в мс: и ключ, и подпись. */
  id: number;
  url: string;
  name: string;
  width: number;
  height: number;
  /** Сам снимок и что в кадре: по кнопке «в фото» он уходит в нейросеть. */
  blob: Blob;
  viewpoint: 'aerial' | 'ground';
  trees: string[];
  shrubs: string[];
}

export type MediaItem =
  | { kind: 'snapshot'; key: string; at: number; shot: Shot }
  | { kind: 'photo'; key: string; at: number; photo: PhotoOut };

export function mediaItems(shots: readonly Shot[], photos: readonly PhotoOut[]): MediaItem[] {
  const items: MediaItem[] = [
    ...shots.map((shot) => ({
      kind: 'snapshot' as const,
      key: `s${String(shot.id)}`,
      at: shot.id,
      shot,
    })),
    ...photos.map((photo) => ({
      kind: 'photo' as const,
      key: `p${photo.id}`,
      at: Date.parse(photo.created_at),
      photo,
    })),
  ];
  return items.sort((a, b) => b.at - a.at);
}

function clockOf(at: number): string {
  return new Date(at).toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' });
}

/** Подпись элемента: что это и когда. */
export function mediaTitle(item: MediaItem): string {
  if (item.kind === 'snapshot') return `Снимок ${clockOf(item.at)}`;
  return item.photo.shot || `Фото ${clockOf(item.at)}`;
}

/** Метка на превью: снимок или фото нейросетью, с фоном ли, в каком оно состоянии. */
export function mediaBadge(item: MediaItem): string {
  if (item.kind === 'snapshot') return 'снимок';
  if (item.photo.state === 'failed') return 'ошибка';
  return item.photo.scenery ? 'ИИ + фон' : 'ИИ';
}
