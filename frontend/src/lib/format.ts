/* Числа и слова для эксперта: запятая вместо точки, русские падежи, минуты словами. */

/** Метры с двумя знаками и запятой: панель читает эксперт, а не отладчик. */
export const meters = (value: number): string => value.toFixed(2).replace('.', ',');

export const decimal = (value: number): string => value.toFixed(2).replace('.', ',');

/** Русское числительное: «1 место», «2 места», «5 мест». Без него подписи приходится строить
 *  так, чтобы обойти падеж, и они кривеют. */
export function plural(count: number, one: string, few: string, many: string): string {
  const tail = count % 10;
  const hundred = count % 100;
  if (tail === 1 && hundred !== 11) return one;
  if (tail >= 2 && tail <= 4 && (hundred < 12 || hundred > 14)) return few;
  return many;
}

/** Время хода прогона: «1:05». */
export function clockText(seconds: number): string {
  const s = Math.max(0, Math.round(seconds));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
}

/** Остаток прогона словами: точные секунды на оценке по весам этапов - ложная точность. */
export function aboutText(seconds: number): string {
  if (seconds < 10) return 'несколько секунд';
  if (seconds < 60) return `около ${Math.ceil(seconds / 10) * 10} с`;
  const minutes = Math.round(seconds / 60);
  return minutes <= 1 ? 'около минуты' : `около ${minutes} мин`;
}

const KIB = 1024;

/** Размер файла словами человека, а не байтами. */
export function humanSize(bytes: number): string {
  if (bytes < KIB) return `${bytes} Б`;
  if (bytes < KIB * KIB) return `${(bytes / KIB).toFixed(0)} КБ`;
  return `${(bytes / KIB / KIB).toFixed(1).replace('.', ',')} МБ`;
}

/** Вклад посадки в индекс качества в промилле. Вклад одной посадки - десятитысячные доли
 *  индекса; меньше половины сотой промилле называется нулём, а не «без неё лучше». */
export function permille(delta: number): { value: number; text: string; zero: boolean } {
  const value = Math.round((Number.isFinite(delta) ? delta : 0) * 1000 * 1e6) / 1e6;
  const zero = Math.abs(value) < 0.005;
  const text = `${value < 0 ? '−' : '+'}${Math.abs(value).toFixed(2).replace('.', ',')} ‰`;
  return { value, text, zero };
}
