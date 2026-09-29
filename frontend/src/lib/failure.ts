/* Неудавшийся прогон словами человека: что случилось, что сделать и сырой текст для разбора.
 *
 * Сервис записывает причину как есть - текстом исключения, и у неполного чертежа это две сотни
 * знаков вида «XREF ...; LWPOLYLINE, слой '...': 3 (missing-acis-data)». Эксперт на странице
 * прогона по ним не поймёт, что делать (жюри дизайна, итерация 7). Поэтому причина - одна
 * строка, действие - по смыслу ошибки, а сырой текст целиком остаётся под раскрытием. */

import { plural } from './format';

export interface Failure {
  /** Что случилось, одной строкой. */
  reason: string;
  /** Что сделать, чтобы следующий прогон удался. */
  action: string;
  /** Текст сервиса целиком, если в нём больше, чем причина; иначе null. */
  details: string | null;
}

interface Family {
  test: RegExp;
  /** Причина словами; без неё - первое предложение текста сервиса. */
  reason?: (raw: string) => string;
  action: string | ((raw: string) => string);
}

const INCOMPLETE = 'Чертёж прочитан не полностью';

/** Причина неполного чертежа. Новый текст сервиса начинается с неё; старые прогоны хранят
 *  перечень пробелов, и число внешних ссылок считается по нему. */
function incompleteReason(raw: string): string {
  if (raw.startsWith(INCOMPLETE)) return firstSentence(raw);
  const list = /^[^:]*:\s*([\s\S]*?)(?:\.\s+Расчёт остановлен[\s\S]*)?$/.exec(raw)?.[1] ?? '';
  const items = list.split('; ').filter(Boolean);
  const xrefs = items.filter((item) => item.startsWith('XREF ')).length;
  const parts: string[] = [];
  if (xrefs) {
    const found = plural(xrefs, 'найдена', 'найдены', 'найдено');
    const links = plural(xrefs, 'внешняя ссылка', 'внешние ссылки', 'внешних ссылок');
    parts.push(`не ${found} ${String(xrefs)} ${links}`);
  }
  if (items.length > xrefs) parts.push('у части объектов нет геометрии');
  return parts.length ? `${INCOMPLETE}: ${parts.join(', ')}.` : `${INCOMPLETE}.`;
}

const FAMILIES: readonly Family[] = [
  {
    test: /^(Неполная геометрия|Чертёж прочитан не полностью)/,
    reason: incompleteReason,
    action: (raw) =>
      /XREF|внешн/.test(raw)
        ? 'Пересохраните DXF вместе с внешними ссылками и запустите снова.'
        : 'Замените неподдерживаемые объекты полилиниями или штриховками, пересохраните DXF и запустите снова.',
  },
  {
    test: /^Требуется уточнить классы объектов/,
    reason: () => 'Сервис не распознал назначение части объектов чертежа.',
    action: 'Уточните объекты на чертеже и запустите прогон снова.',
  },
  {
    test: /^XREF .*не предоставлен|^Склейка|^Комплект из нескольких|комплект улицы не скопирован/,
    action: 'Соберите комплект заново: основной чертёж и все файлы его внешних ссылок.',
  },
  {
    test: /не является корректным DXF|^Не удалось открыть|ожидается DXF или DWG|аудит DXF/i,
    action: 'Пересохраните чертёж в CAD как DXF и запустите снова.',
  },
  {
    test: /конвертер|DWG -> DXF|перевести чертёж/i,
    action: 'Сохраните чертёж в CAD как DXF и загрузите его вместо DWG.',
  },
  {
    // Необработанное исключение: сервис пишет «ИмяОшибки: текст».
    test: /^[A-Za-z_][\w.]*(Error|Exception)\b/,
    reason: () => 'Расчёт остановила внутренняя ошибка сервиса.',
    action:
      'Запустите прогон снова. Если ошибка повторится, передайте подробности команде сервиса.',
  },
];

/** Первое предложение: до точки, за которой идёт новое предложение с заглавной буквы. */
export function firstSentence(text: string): string {
  const match = /^([\s\S]+?[.!?])\s+(?=[А-ЯЁA-Z«])/.exec(text);
  return (match?.[1] ?? text).trim();
}

export function explainFailure(error: string | null | undefined): Failure {
  const raw = (error ?? '').trim();
  if (!raw) {
    return {
      reason: 'Сервис не записал причину.',
      action: 'Запустите прогон снова с консоли.',
      details: null,
    };
  }
  const family = FAMILIES.find((item) => item.test.test(raw));
  const reason = family?.reason ? family.reason(raw) : firstSentence(raw);
  const action = family
    ? typeof family.action === 'string'
      ? family.action
      : family.action(raw)
    : 'Проверьте чертёж и параметры по тексту ошибки и запустите прогон снова.';
  return { reason, action, details: raw === reason ? null : raw };
}
