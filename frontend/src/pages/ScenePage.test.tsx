import { act, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { mockApi, run } from '../test/api';
import { renderApp } from '../test/render';
import { keys } from '../api/queries';
import * as world from '../scene3d/world';

vi.mock('../components/run/PlanMap', () => ({
  PlanMap: () => <canvas aria-label="План посадок" />,
}));

// jsdom не даёт WebGL: сцену проверяют модульные тесты движка и живой браузер. Здесь - что
// страница честно говорит, почему сцены нет, и ведёт обратно к плану.
describe('3D-вид прогона', () => {
  it(
    'загрузка основного плана для схемы не пересобирает готовый мир из scene.json',
    { timeout: 30_000 },
    async () => {
      const build = vi.spyOn(world, 'buildWorld');
      mockApi({
        '/api/v1/runs/r1': run({
          artifacts: ['scene.json', 'plan.json'].map((name) => ({ name, url: '', size_bytes: 1 })),
        }),
        '/api/v1/runs/r1/artifacts/scene.json': {
          version: 1,
          extent: [0, 0, 100, 100],
          counts: {},
          buildings: [],
          plants: [],
          species: {},
        },
      });
      const { client } = renderApp('/runs/r1/3d');
      await waitFor(
        () => {
          expect(build).toHaveBeenCalled();
        },
        { timeout: 20_000 },
      );
      const builds = build.mock.calls.length;
      await act(async () => {
        client.setQueryData(keys.artifact('r1', 'plan.json'), { placements: [], rejections: [] });
        await new Promise((resolve) => setTimeout(resolve, 20));
      });
      expect(build).toHaveBeenCalledTimes(builds);
    },
  );

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
      // Шапка прогона - та же, что на плане: переключатель «План / 3D-вид».
      expect(await screen.findByRole('link', { name: 'План' })).toHaveAttribute('href', '/runs/r1');
      expect(screen.getByRole('link', { name: '3D и фото' })).toHaveAttribute(
        'aria-current',
        'page',
      );
    },
  );

  it('шапка прогона ведёт в 3D, только когда план готов', { timeout: 30_000 }, async () => {
    mockApi({ '/api/v1/runs/r1': run() });
    const first = renderApp('/runs/r1');
    expect(
      await screen.findByRole('link', { name: /3D и фото/ }, { timeout: 20_000 }),
    ).toHaveAttribute('href', '/runs/r1/3d');
    // Один вход в 3D: кадры улицы - кнопкой внутри 3D-вида.
    expect(screen.queryByRole('link', { name: /кадры улицы/ })).not.toBeInTheDocument();
    first.unmount();
    mockApi({ '/api/v1/runs/r1': run({ state: 'running' }) });
    renderApp('/runs/r1');
    expect((await screen.findAllByText(/Тестовая улица/)).length).toBeGreaterThan(0);
    expect(screen.queryByRole('link', { name: /3D и фото/ })).not.toBeInTheDocument();
  });
});
