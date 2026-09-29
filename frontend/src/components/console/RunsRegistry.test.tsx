import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';

import type { RunOut } from '../../api/types';
import { type Call, consoleRoutes, mockApi, run } from '../../test/api';
import { renderApp } from '../../test/render';

const LIST = '/api/v1/runs?limit=12';

/** Реестр из четырёх прогонов во всех состояниях; DELETE убирает прогон из списка сервера. */
function registry(onDelete?: (id: string) => Response) {
  let items: RunOut[] = [
    run({ id: 'r-ok', state: 'succeeded', source_name: 'Готовая.dxf' }),
    run({ id: 'r-bad', state: 'failed', source_name: 'Упавшая.dxf', summary: {} }),
    run({ id: 'r-run', state: 'running', source_name: 'Считается.dxf', summary: {} }),
    run({ id: 'r-wait', state: 'queued', source_name: 'В очереди.dxf', summary: {} }),
  ];
  const remove = (id: string) => {
    const answer = onDelete?.(id) ?? new Response(null, { status: 204 });
    if (answer.ok) items = items.filter((item) => item.id !== id);
    return answer;
  };
  return mockApi({
    ...consoleRoutes(),
    [LIST]: () => Response.json({ items }),
    'DELETE /api/v1/runs/r-ok': () => remove('r-ok'),
    'DELETE /api/v1/runs/r-bad': () => remove('r-bad'),
  });
}

const deletes = (calls: Call[]) => calls.filter((c) => c.method === 'DELETE');

describe('удаление прогона из реестра', () => {
  it('кнопка «Удалить» есть у готового и упавшего прогона, у идущего и ждущего - нет', async () => {
    registry();
    renderApp('/');

    expect(await screen.findByRole('button', { name: 'Удалить прогон Готовая' })).toBeVisible();
    expect(screen.getByRole('button', { name: 'Удалить прогон Упавшая' })).toBeVisible();
    expect(screen.queryByRole('button', { name: 'Удалить прогон Считается' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Удалить прогон В очереди' })).toBeNull();
    expect(screen.getAllByRole('button', { name: /^Удалить прогон/ })).toHaveLength(2);
  });

  it('первый клик только спрашивает, второй удаляет, и строка уходит без перезагрузки', async () => {
    const calls = registry();
    renderApp('/');
    const user = userEvent.setup();

    await user.click(await screen.findByRole('button', { name: 'Удалить прогон Упавшая' }));

    const confirm = screen.getByRole('button', { name: 'Точно удалить прогон Упавшая?' });
    expect(confirm).toHaveFocus();
    expect(deletes(calls)).toHaveLength(0);

    await user.click(confirm);

    await waitFor(() => {
      expect(screen.queryByRole('link', { name: 'Упавшая' })).toBeNull();
    });
    expect(deletes(calls).map((c) => c.url)).toEqual(['/api/v1/runs/r-bad']);
    expect(screen.getByRole('link', { name: 'Готовая' })).toBeVisible();
    expect(screen.getByRole('link', { name: 'Считается' })).toBeVisible();
  });

  it('отмена, Escape и уход фокуса снимают подтверждение и ничего не удаляют', async () => {
    const calls = registry();
    renderApp('/');
    const user = userEvent.setup();

    const trash = await screen.findByRole('button', { name: 'Удалить прогон Готовая' });
    const confirmOf = () => screen.queryByRole('button', { name: 'Точно удалить прогон Готовая?' });

    await user.click(trash);
    expect(trash).toHaveAttribute('aria-expanded', 'true');
    await user.click(screen.getByRole('button', { name: 'Отмена' }));
    expect(confirmOf()).toBeNull();
    expect(trash).toHaveAttribute('aria-expanded', 'false');
    expect(trash).toHaveFocus();

    await user.click(trash);
    expect(confirmOf()).toHaveFocus();
    await user.keyboard('{Escape}');
    expect(confirmOf()).toBeNull();
    expect(trash).toHaveFocus();

    // Фокус ушёл к другой строке - подтверждение первой снимается.
    await user.click(trash);
    await user.click(screen.getByRole('button', { name: 'Удалить прогон Упавшая' }));
    expect(confirmOf()).toBeNull();
    expect(screen.getByRole('button', { name: 'Точно удалить прогон Упавшая?' })).toHaveFocus();

    expect(deletes(calls)).toHaveLength(0);
    expect(screen.getByRole('link', { name: 'Готовая' })).toBeVisible();
  });

  it('отказ сервера оставляет строку и называет причину', async () => {
    registry(() =>
      Response.json(
        {
          title: 'Состояние прогона изменилось',
          status: 409,
          detail: 'Прогон ещё идёт: удалить можно только законченный прогон.',
        },
        { status: 409, headers: { 'content-type': 'application/problem+json' } },
      ),
    );
    renderApp('/');
    const user = userEvent.setup();

    await user.click(await screen.findByRole('button', { name: 'Удалить прогон Готовая' }));
    await user.click(screen.getByRole('button', { name: 'Точно удалить прогон Готовая?' }));

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent(
      'Прогон не удалён: Прогон ещё идёт: удалить можно только законченный прогон.',
    );
    const row = screen.getByRole('link', { name: 'Готовая' }).closest('tr');
    expect(row).not.toBeNull();
    expect(
      within(row as HTMLElement).getByRole('button', { name: 'Удалить прогон Готовая' }),
    ).toBeVisible();
  });
});
