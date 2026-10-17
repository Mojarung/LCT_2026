/* Числа и слова для эксперта: запятая вместо точки, русские падежи, минуты словами. */

/* Числа форматирует Intl по русской норме: запятая в дроби, разряды через неразрывный пробел
 * начиная с пяти знаков («18 780», «13 567,52»), четырёхзначные слитно («1964»): разорванное
 * «1 964» в крупном моноширинном числе читается как две цифры. Координаты генплана бывают
 * пятизначными, и без разрядов их приходится пересчитывать по цифрам. */
const TWO = new Intl.NumberFormat('ru-RU', {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
  useGrouping: 'min2',
});
const ONE = new Intl.NumberFormat('ru-RU', {
  minimumFractionDigits: 1,
  maximumFractionDigits: 1,
  useGrouping: 'min2',
});
const WHOLE = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0, useGrouping: 'min2' });
const PLAIN = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 2, useGrouping: 'min2' });
const STAMP = new Intl.DateTimeFormat('ru-RU', {
  day: '2-digit',
  month: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
});

/** Метры с двумя знаками и запятой: панель читает эксперт, а не отладчик. */
export const meters = (value: number): string => TWO.format(value);

export const decimal = (value: number): string => TWO.format(value);

/** Число без лишних нулей: «6», «5,5», «1,25». */
export const plain = (value: number): string => PLAIN.format(value);

/** Целое число с разрядами: «18 780 посадок». */
export const integer = (value: number): string => WHOLE.format(value);

/** Время прогона по часам человека, а не сервера: «23.09, 12:15». */
export const stamp = (iso: string): string => STAMP.format(new Date(iso));

/** Имя чертежа без расширения: «.dxf» у каждого прогона ничего не различает - ни в заголовке
 *  прогона, ни в реестре консоли. Пробел перед дефисом неразрывный: строка не начинается с
 *  дефиса при переносе. */
export const drawingName = (name: string): string =>
  repairCp1251(name)
    .replace(/\.(dxf|dwg)$/i, '')
    .replaceAll(' - ', '\u00a0- ');

/** \u0418\u043c\u044f \u0444\u0430\u0439\u043b\u0430 \u0432 cp1251, \u043f\u0440\u043e\u0447\u0438\u0442\u0430\u043d\u043d\u043e\u0435 \u043a\u0430\u043a latin-1 (\u0430\u0440\u0445\u0438\u0432\u044b \u0441 Windows): \u00ab\u00d2\u00ee\u00ef\u00ee\u00e3\u00f0\u00e0\u00f4\u00e8\u00ff\u00bb \u0432\u043c\u0435\u0441\u0442\u043e
 *  \u00ab\u0422\u043e\u043f\u043e\u0433\u0440\u0430\u0444\u0438\u044f\u00bb. \u0412 cp1251 \u0431\u0443\u043a\u0432\u044b \u0410-\u044f \u043b\u0435\u0436\u0430\u0442 \u043f\u043e\u0434\u0440\u044f\u0434 \u0432 0xC0-0xFF, \u0401 \u0438 \u0451 - \u0432 0xA8 \u0438 0xB8, \u043f\u043e\u044d\u0442\u043e\u043c\u0443
 *  \u0441\u0434\u0432\u0438\u0433 \u043d\u0430 0x350 \u0432\u043e\u0437\u0432\u0440\u0430\u0449\u0430\u0435\u0442 \u043a\u0438\u0440\u0438\u043b\u043b\u0438\u0446\u0443. \u0427\u0438\u043d\u0438\u0442\u0441\u044f, \u0442\u043e\u043b\u044c\u043a\u043e \u0435\u0441\u043b\u0438 \u043a\u0438\u0440\u0438\u043b\u043b\u0438\u0446\u044b \u0432 \u0438\u043c\u0435\u043d\u0438 \u043d\u0435\u0442 \u0432\u043e\u0432\u0441\u0435, \u0430
 *  \u0442\u0430\u043a\u0438\u0445 \u0437\u043d\u0430\u043a\u043e\u0432 \u043d\u0435 \u043c\u0435\u043d\u044c\u0448\u0435 \u0442\u0440\u0451\u0445: \u0444\u0440\u0430\u043d\u0446\u0443\u0437\u0441\u043a\u043e\u0435 \u00ab\u00e9\u00bb \u0432 \u0438\u043c\u0435\u043d\u0438 \u043e\u0441\u0442\u0430\u0451\u0442\u0441\u044f \u043a\u0430\u043a \u0435\u0441\u0442\u044c. */
export function repairCp1251(name: string): string {
  if (/[\u0400-\u04ff]/u.test(name)) return name;
  if ((name.match(/[\u00c0-\u00ff]/gu)?.length ?? 0) < 3) return name;
  return name.replace(/[\u00a8\u00b8\u00c0-\u00ff]/gu, (c) => {
    if (c === '\u00a8') return '\u0401';
    if (c === '\u00b8') return '\u0451';
    return String.fromCharCode(c.charCodeAt(0) + 0x350);
  });
}

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
  if (bytes < KIB * KIB) return `${WHOLE.format(bytes / KIB)} КБ`;
  return `${ONE.format(bytes / KIB / KIB)} МБ`;
}

/** Вклад посадки в индекс качества в промилле. Вклад одной посадки - десятитысячные доли
 *  индекса; меньше половины сотой промилле называется нулём, а не «без неё лучше». */
export function permille(delta: number): { value: number; text: string; zero: boolean } {
  const value = Math.round((Number.isFinite(delta) ? delta : 0) * 1000 * 1e6) / 1e6;
  const zero = Math.abs(value) < 0.005;
  const text = `${value < 0 ? '−' : '+'}${TWO.format(Math.abs(value))} ‰`;
  return { value, text, zero };
}
