/** Предупреждения, которые меняют смысл всего плана, а не уточняют деталь. На улице без
 *  границы работ сервис засаживает весь чертёж, и «18 780 посадок» читается как результат,
 *  пока не сказать обратного. То же с комплектом из несовпавших листов и чертежом без сетей. */
export const KEY_WARNINGS = [
  'Граница работ не найдена',
  'Склейка: габариты',
  'В чертеже нет подземных сетей',
] as const;

export function keyNotices(warnings: readonly string[]): string[] {
  return warnings.filter((text) => KEY_WARNINGS.some((prefix) => text.startsWith(prefix)));
}
