import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';

import { consoleRoutes, mockApi, run } from '../test/api';
import { renderApp } from '../test/render';

const formOf = (calls: { method: string; url: string; init: RequestInit | undefined }[]) => {
  const post = calls.find((c) => c.method === 'POST' && c.url === '/api/v1/runs');
  expect(post, 'форма ушла на POST /api/v1/runs').toBeDefined();
  return post?.init?.body as FormData;
};

describe('консоль запуска', () => {
  it('улица из каталога уходит полем street, без файла, и ведёт на страницу прогона', async () => {
    const calls = mockApi({
      ...consoleRoutes(),
      'POST /api/v1/runs': () =>
        Response.json(run({ id: 'r42', state: 'queued' }), { status: 202 }),
    });
    const { router } = renderApp('/');
    const user = userEvent.setup();

    await user.selectOptions(
      await screen.findByLabelText('Улица пилотного проекта'),
      '07-test-street',
    );
    await user.click(screen.getByRole('button', { name: 'Запустить прогон' }));

    await waitFor(() => {
      expect(router.state.location.pathname).toBe('/runs/r42');
    });
    const form = formOf(calls);
    expect(form.get('street')).toBe('07-test-street');
    expect(form.has('file')).toBe(false);
    expect(form.get('profile')).toBe('strict');
  });

  it('без улицы и файла объясняет, что выбрать, и ничего не отправляет', async () => {
    const calls = mockApi(consoleRoutes());
    renderApp('/');
    const user = userEvent.setup();

    await screen.findByLabelText('Улица пилотного проекта');
    await user.click(screen.getByRole('button', { name: 'Запустить прогон' }));

    expect(
      await screen.findByText('Выберите улицу пилотного проекта или свой чертёж.'),
    ).toBeVisible();
    expect(calls.some((c) => c.method === 'POST')).toBe(false);
  });

  it('нетронутая форма не шлёт overrides: работает выбранный профиль как есть', async () => {
    const calls = mockApi({
      ...consoleRoutes(),
      'POST /api/v1/runs': () => Response.json(run({ id: 'r1' })),
    });
    renderApp('/');
    const user = userEvent.setup();

    await user.selectOptions(
      await screen.findByLabelText('Улица пилотного проекта'),
      '07-test-street',
    );
    await screen.findByDisplayValue('5');
    await user.click(screen.getByRole('button', { name: 'Запустить прогон' }));

    await waitFor(() => {
      expect(formOf(calls).has('overrides')).toBe(false);
    });
  });

  it('параметры свёрнуты: заголовок раскрытия называет профиль и шаг и говорит о правке', async () => {
    mockApi(consoleRoutes());
    renderApp('/');
    const user = userEvent.setup();

    const summary = await screen.findByText(/^Параметры: strict, шаг 5 м$/);
    expect(summary.closest('details')).not.toHaveAttribute('open');
    await user.click(screen.getByRole('checkbox', { name: /Добор зоны/ }));
    expect(summary).toHaveTextContent('Параметры: strict, шаг 5 м, изменены');
  });

  it('снятая галочка добора уходит изменением приёмов профиля', async () => {
    const calls = mockApi({
      ...consoleRoutes(),
      'POST /api/v1/runs': () => Response.json(run({ id: 'r1' })),
    });
    renderApp('/');
    const user = userEvent.setup();

    await user.selectOptions(
      await screen.findByLabelText('Улица пилотного проекта'),
      '07-test-street',
    );
    const fill = await screen.findByRole('checkbox', { name: /Добор зоны/ });
    await waitFor(() => {
      expect(fill).toBeChecked();
    });
    await user.click(fill);
    await user.click(screen.getByRole('button', { name: 'Запустить прогон' }));

    await waitFor(() => {
      expect(JSON.parse(formOf(calls).get('overrides') as string)).toEqual({
        modes: ['alley', 'lawn'],
      });
    });
  });

  it('форма показывает значения выбранного профиля, а не свои', async () => {
    mockApi(consoleRoutes());
    renderApp('/');
    const user = userEvent.setup();

    await screen.findByRole('option', { name: 'shrubs' });
    await user.selectOptions(screen.getByLabelText('Профиль норм'), 'shrubs');

    expect(await screen.findByDisplayValue('1')).toBeInTheDocument();
    expect(screen.getByRole('checkbox', { name: /Добор зоны/ })).not.toBeChecked();
  });

  it('пока форма уходит, кнопка занята и говорит, что происходит', async () => {
    let answer: (response: Response) => void = () => undefined;
    mockApi({
      ...consoleRoutes(),
      'POST /api/v1/runs': () =>
        new Promise<Response>((resolve) => {
          answer = resolve;
        }),
    });
    renderApp('/');
    const user = userEvent.setup();

    await user.selectOptions(
      await screen.findByLabelText('Улица пилотного проекта'),
      '07-test-street',
    );
    await user.click(screen.getByRole('button', { name: 'Запустить прогон' }));

    const busy = await screen.findByRole('button', { name: 'Готовим улицу…' });
    expect(busy).toBeDisabled();
    answer(Response.json(run({ id: 'r1' })));
  });

  it('ошибка сервера показывается его словами', async () => {
    mockApi({
      ...consoleRoutes(),
      'POST /api/v1/runs': () =>
        new Response(
          JSON.stringify({
            title: 'Unprocessable Content',
            status: 422,
            detail: 'Улицы x нет в каталоге',
          }),
          { status: 422, headers: { 'content-type': 'application/problem+json' } },
        ),
    });
    renderApp('/');
    const user = userEvent.setup();

    await user.selectOptions(
      await screen.findByLabelText('Улица пилотного проекта'),
      '07-test-street',
    );
    await user.click(screen.getByRole('button', { name: 'Запустить прогон' }));

    expect(await screen.findByText('Улицы x нет в каталоге')).toBeVisible();
    expect(screen.getByRole('button', { name: 'Запустить прогон' })).toBeEnabled();
  });

  it('без каталога улиц предлагает встроенный участок и запускает его через API', async () => {
    const calls = mockApi({
      ...consoleRoutes({ streets: [] }),
      'POST /api/v1/runs/demo': () => Response.json(run({ id: 'demo1', state: 'queued' })),
    });
    const { router } = renderApp('/');
    const user = userEvent.setup();

    await user.click(
      await screen.findByRole('button', { name: 'Запустить на встроенном участке' }),
    );

    await waitFor(() => {
      expect(router.state.location.pathname).toBe('/runs/demo1');
    });
    expect(calls.some((c) => c.method === 'POST' && c.url === '/api/v1/runs/demo')).toBe(true);
  });

  it('что применяется: числа свода из /meta', async () => {
    mockApi(consoleRoutes());
    renderApp('/');

    const facts = await screen.findByRole('region', { name: 'Что применяется' });
    await waitFor(() => {
      expect(within(facts).getByText('76')).toBeInTheDocument();
    });
    expect(within(facts).getByText('75')).toBeInTheDocument();
    expect(within(facts).getByText('1')).toBeInTheDocument();
  });

  it('последние прогоны - ссылками на их страницы', async () => {
    mockApi({
      ...consoleRoutes(),
      '/api/v1/runs?limit=12': { items: [run({ id: 'r7', source_name: 'Берзарина.dxf' })] },
    });
    renderApp('/');

    const link = await screen.findByRole('link', { name: 'Берзарина.dxf' });
    expect(link).toHaveAttribute('href', '/runs/r7');
  });
});
