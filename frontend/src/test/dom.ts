/* Чего нет в jsdom. Отдельный модуль, чтобы заглушки встали раньше импортов приложения. */

// jsdom не знает медиазапросов и наблюдателя размеров. Заглушки ведут себя как широкий экран,
// размер которого не меняется. Хранилище рабочего места читает медиазапрос
// уже при импорте.
if (typeof window.matchMedia !== 'function') {
  Object.defineProperty(window, 'matchMedia', {
    configurable: true,
    value: (query: string): MediaQueryList => ({
      matches: false,
      media: query,
      onchange: null,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
      addListener: () => undefined,
      removeListener: () => undefined,
      dispatchEvent: () => false,
    }),
  });
}

class StillResizeObserver implements ResizeObserver {
  observe(): void {
    /* размер в jsdom не меняется */
  }
  unobserve(): void {
    /* нечего снимать */
  }
  disconnect(): void {
    /* нечего снимать */
  }
}
if (typeof globalThis.ResizeObserver === 'undefined')
  globalThis.ResizeObserver = StillResizeObserver;

export {};
