import { screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { mockApi, run } from '../test/api';
import { renderApp } from '../test/render';

vi.mock('../components/run/PlanMap', () => ({
  PlanMap: () => <canvas aria-label="План посадок" />,
}));

// jsdom не даёт WebGL: сцену проверяют модульные тесты движка и живой браузер. Здесь - что
// страница честно говорит, почему сцены нет, и ведёт обратно к плану.
describe('3D-вид прогона', () => {
  it(
    'без WebGL объясняет, что 3D недоступно, и даёт вернуться к плану',
    { timeout: 30_000 },
    async () => {
      mockApi({ '/api/v1/runs/r1': run() });
      renderApp('/runs/r1/3d');
      // Страница - ленивый чанк с three.js: под нагрузкой всего набора он грузится секунды.
      expect(
        await screen.findByText(/нет WebGL 2/, undefined, { timeout: 20_000 }),
      ).toBeInTheDocument();
      expect(screen.getByRole('link', { name: '← к плану прогона' })).toHaveAttribute(
        'href',
        '/runs/r1',
      );
      expect(screen.getByRole('link', { name: '← план прогона' })).toHaveAttribute(
        'href',
        '/runs/r1',
      );
    },
  );

  it('шапка прогона ведёт в 3D, только когда план готов', async () => {
    mockApi({ '/api/v1/runs/r1': run() });
    const first = renderApp('/runs/r1');
    expect(await screen.findByRole('link', { name: /3D и снимки/ })).toHaveAttribute(
      'href',
      '/runs/r1/3d',
    );
    expect(screen.getByRole('link', { name: /кадры улицы/ })).toHaveAttribute(
      'href',
      '/runs/r1/3d?shots=street',
    );
    first.unmount();
    mockApi({ '/api/v1/runs/r1': run({ state: 'running' }) });
    renderApp('/runs/r1');
    expect(await screen.findByText(/Тестовая улица/)).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: /3D и снимки/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('link', { name: /кадры улицы/ })).not.toBeInTheDocument();
  });
});
