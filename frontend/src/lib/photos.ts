/* Фото нейросетью: подгонка снимка под модель и ход задания для полосы загрузки.
 *
 * Модель ждёт кадр 16:9 со сторонами, кратными 32; снимок экрана бывает любого размера,
 * поэтому он обрезается по центру и сжимается до 1024 x 576. Сколько ждать - по прошлым фото
 * этого сервера: время генерации зависит от видеокарты, а не от кадра. */

import type { PhotoOut } from '../api/types';

export const PHOTO_WIDTH = 1024;
export const PHOTO_HEIGHT = 576;
/** Сколько ждать, пока своих замеров нет: RTX 5070 при потолке 6 ГБ, docs/notes/40. */
export const PHOTO_SECONDS_DEFAULT = 80;
/** Полоса не доходит до конца, пока модель не ответила: оценка - не обещание. */
const PROGRESS_CAP = 0.95;

export interface Crop {
  sx: number;
  sy: number;
  sw: number;
  sh: number;
}

/** Часть снимка w x h, которая после масштаба закрывает кадр tw x th без полей. */
export function coverCrop(w: number, h: number, tw: number, th: number): Crop {
  const target = tw / th;
  if (w / h > target) {
    const sw = Math.round(h * target);
    return { sx: Math.round((w - sw) / 2), sy: 0, sw, sh: h };
  }
  const sh = Math.round(w / target);
  return { sx: 0, sy: Math.round((h - sh) / 2), sw: w, sh };
}

/** Медиана времени последних готовых фото; без них - замер из заметки. */
export function expectedSeconds(photos: readonly PhotoOut[]): number {
  const done = photos
    .filter((p) => p.state === 'succeeded' && p.seconds)
    .slice(0, 5)
    .map((p) => p.seconds ?? 0)
    .sort((a, b) => a - b);
  if (!done.length) return PHOTO_SECONDS_DEFAULT;
  return done[done.length >> 1] ?? PHOTO_SECONDS_DEFAULT;
}

export interface Progress {
  /** Доля готовности 0..1 для полосы; у ждущего в очереди - 0. */
  share: number;
  /** Что написать под полосой. */
  label: string;
}

/** Ход задания: очередь считается по заданиям, созданным раньше и ещё не законченным. */
export function photoProgress(
  photo: PhotoOut,
  all: readonly PhotoOut[],
  now: number,
  expected: number,
): Progress {
  if (photo.state === 'queued') {
    const ahead = all.filter(
      (p) =>
        (p.state === 'queued' || p.state === 'running') &&
        p.id !== photo.id &&
        Date.parse(p.created_at) < Date.parse(photo.created_at),
    ).length;
    return { share: 0, label: ahead ? `в очереди, перед ним ${String(ahead)}` : 'в очереди' };
  }
  if (photo.state === 'running' && photo.started_at) {
    const elapsed = Math.max(0, (now - Date.parse(photo.started_at)) / 1000);
    const left = Math.max(0, Math.round(expected - elapsed));
    return {
      share: Math.min(PROGRESS_CAP, elapsed / expected),
      label: left > 0 ? `модель рисует, осталось около ${String(left)} с` : 'модель дорисовывает',
    };
  }
  if (photo.state === 'succeeded') return { share: 1, label: 'готово' };
  return { share: 0, label: photo.error ? `не удалось: ${photo.error}` : 'не удалось' };
}

/** Снимок любого размера -> PNG 1024 x 576 для модели: центр кадра без полей. */
export async function fitForPhoto(image: Blob): Promise<Blob> {
  const bitmap = await createImageBitmap(image);
  try {
    const crop = coverCrop(bitmap.width, bitmap.height, PHOTO_WIDTH, PHOTO_HEIGHT);
    const canvas = document.createElement('canvas');
    canvas.width = PHOTO_WIDTH;
    canvas.height = PHOTO_HEIGHT;
    const ctx = canvas.getContext('2d');
    if (!ctx) throw new Error('Браузер не дал холст для подготовки снимка');
    ctx.drawImage(bitmap, crop.sx, crop.sy, crop.sw, crop.sh, 0, 0, PHOTO_WIDTH, PHOTO_HEIGHT);
    const blob = await new Promise<Blob | null>((resolve) => {
      canvas.toBlob(resolve, 'image/png');
    });
    if (!blob) throw new Error('Браузер не отдал подготовленный снимок');
    return blob;
  } finally {
    bitmap.close();
  }
}
