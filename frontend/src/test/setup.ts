import '@testing-library/jest-dom/vitest';
// Заглушки DOM - до любого импорта приложения: модули читают медиазапросы при загрузке.
import './dom';

import { cleanup, configure } from '@testing-library/react';
import { afterEach, beforeEach, vi } from 'vitest';

import { resetWorkspace } from '../state/workspace';

// findBy/waitFor ждут до 5 с, а не 1 с по умолчанию: первый тест файла рендерит приложение
// целиком, и в полном прогоне, когда воркеры делят процессор, это дольше секунды. Такие тесты
// падали только в полном наборе и проходили поодиночке.
configure({ asyncUtilTimeout: 5000 });

// Тесты не ходят в сеть: любой запрос, который тест не подменил сам, получает 404.
beforeEach(() => {
  vi.stubGlobal(
    'fetch',
    vi.fn(() =>
      Promise.resolve(
        new Response(JSON.stringify({ title: 'Not Found', status: 404, detail: 'нет в тесте' }), {
          status: 404,
          headers: { 'content-type': 'application/problem+json' },
        }),
      ),
    ),
  );
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  // Хранилище чистится до сброса рабочего места: оно читает сохранённые панели и стиль карты,
  // и выбор одного теста иначе становился начальным состоянием следующего.
  localStorage.clear();
  sessionStorage.clear();
  resetWorkspace();
  document.documentElement.removeAttribute('data-theme');
  document.documentElement.removeAttribute('data-map-style');
  document.body.className = '';
});
