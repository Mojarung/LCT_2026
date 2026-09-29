/* Стиль карты плана. Основной - инженерный чертёж: условные знаки дендроплана и
 * разбивочно-посадочного чертежа пилота (signs.ts), плоские заливки, без фактур и теней -
 * так план сразу читает дендролог, проектировщик и проверяющий. Иллюстрированный (кроны
 * моделей, бумага, тени, как на слайдах) - вторым, по кнопке у кромки карты.
 *
 * Стиль живёт атрибутом data-map-style на <html>: по нему CSS меняет токены подосновы
 * (tokens.css), а движок карты перерисовывается (MutationObserver в engine.ts). Без атрибута
 * стиль инженерный - так же считают и CSS, и движок. */

export type MapStyle = 'engineering' | 'illustrated';

/** Ключ localStorage; его же до первой отрисовки читает index.html, чтобы карта не мигала. */
export const MAP_STYLE_KEY = 'green-map-style';

export function parseMapStyle(value: string | null | undefined): MapStyle {
  return value === 'illustrated' ? 'illustrated' : 'engineering';
}

/** Действующий стиль документа. */
export function documentMapStyle(root: HTMLElement = document.documentElement): MapStyle {
  return parseMapStyle(root.dataset.mapStyle);
}
