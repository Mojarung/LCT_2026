import { QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import { MemoryRouter } from 'react-router';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { makeQueryClient } from '../../api/queryClient';
import { REPORT, REVIEW } from '../../lib/__fixtures__/review';
import { mockApi, run } from '../../test/api';
import { SemanticReviewPanel } from './SemanticReviewPanel';

const engine = vi.hoisted(() => ({
  current: {
    setSemanticReview: vi.fn(),
    focusSemanticReview: vi.fn().mockReturnValue(true),
    restoreSemanticReviewView: vi.fn(),
  },
}));
vi.mock('../../state/engine', () => ({ useEngine: () => engine }));

const source = run({
  overrides: { spacing_m: 6 },
  artifacts: ['semantic-review.geojson', 'classification.json', 'review-input.dxf'].map((name) => ({
    name,
    size_bytes: 100,
    url: `/api/v1/runs/r1/artifacts/${name}`,
  })),
});
const routes = {
  '/api/v1/runs/r1/artifacts/semantic-review.geojson': REVIEW,
  '/api/v1/runs/r1/artifacts/classification.json': REPORT,
};
function Harness() {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button
        onClick={() => {
          setOpen(true);
        }}
      >
        Открыть
      </button>
      <SemanticReviewPanel
        run={source}
        open={open}
        onClose={() => {
          setOpen(false);
        }}
      />
    </>
  );
}
function setup() {
  const client = makeQueryClient();
  client.setDefaultOptions({ queries: { retry: false } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <Harness />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}
beforeEach(() => {
  vi.clearAllMocks();
});
describe('уточнение объектов поверх основного плана', () => {
  it('не загружает тяжёлую геометрию до открытия и не выбирает случайную первую группу', async () => {
    const user = userEvent.setup();
    const calls = mockApi(routes);
    setup();
    expect(calls).toHaveLength(0);
    await user.click(screen.getByRole('button', { name: 'Открыть' }));
    expect(await screen.findByText('Выберите слой в таблице')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Приблизить выбранное' })).toBeDisabled();
    expect(engine.current.setSemanticReview).toHaveBeenLastCalledWith({
      selected: [],
      changed: [],
    });
    expect(engine.current.focusSemanticReview).not.toHaveBeenCalled();
  });
  it('показывает исходную геометрию на плане и просит показать её автоматически и по кнопке', async () => {
    const user = userEvent.setup();
    mockApi(routes);
    setup();
    await user.click(screen.getByRole('button', { name: 'Открыть' }));
    await user.click(await screen.findByRole('button', { name: 'Показать слой 0, группа 1' }));
    expect(engine.current.setSemanticReview).toHaveBeenLastCalledWith({
      selected: [REVIEW.features[0]?.geometry, REVIEW.features[2]?.geometry],
      changed: [],
    });
    expect(engine.current.focusSemanticReview).toHaveBeenLastCalledWith([0, 0, 20, 12], true);
    await user.click(screen.getByRole('button', { name: 'Приблизить выбранное' }));
    expect(engine.current.focusSemanticReview).toHaveBeenLastCalledWith([0, 0, 20, 12], false);
  });
  it('выбирает группу кликом на тип в строке, кнопка не вызывает повторный выбор', async () => {
    const user = userEvent.setup();
    mockApi(routes);
    setup();
    await user.click(screen.getByRole('button', { name: 'Открыть' }));
    await user.click(await screen.findByText('Неизвестно'));
    expect(engine.current.focusSemanticReview).toHaveBeenCalledTimes(1);
    expect(screen.getByRole('button', { name: 'Показать слой 0, группа 1' })).toHaveAttribute(
      'aria-pressed',
      'true',
    );
    await user.click(screen.getByRole('button', { name: 'Показать слой 0, группа 1' }));
    expect(engine.current.focusSemanticReview).toHaveBeenCalledTimes(2);
    await user.selectOptions(screen.getByLabelText('Новый тип: 0, группа 1'), 'fence');
    expect(engine.current.focusSemanticReview).toHaveBeenCalledTimes(2);
  });
  it('обходит отдельные объекты, возвращает обзор, назначение в таблице действует на всю группу', async () => {
    const user = userEvent.setup();
    mockApi(routes);
    setup();
    await user.click(screen.getByRole('button', { name: 'Открыть' }));
    await user.click(await screen.findByRole('button', { name: 'Показать слой 0, группа 1' }));
    await user.click(screen.getByRole('button', { name: 'Следующий объект группы' }));
    expect(screen.getByText('Объект 1 из 2')).toBeInTheDocument();
    expect(engine.current.setSemanticReview).toHaveBeenLastCalledWith({
      selected: [REVIEW.features[0]?.geometry],
      changed: [],
    });
    await user.click(screen.getByRole('button', { name: 'Следующий объект группы' }));
    expect(screen.getByText('Объект 2 из 2')).toBeInTheDocument();
    expect(engine.current.setSemanticReview).toHaveBeenLastCalledWith({
      selected: [REVIEW.features[2]?.geometry],
      changed: [],
    });
    await user.click(screen.getByRole('button', { name: 'Вернуться к предыдущему виду' }));
    expect(engine.current.restoreSemanticReviewView).toHaveBeenCalledTimes(1);
    await user.selectOptions(screen.getByLabelText('Новый тип: 0, группа 1'), 'fence');
    expect(screen.getByText('Назначений к применению: 2')).toBeInTheDocument();
    expect(screen.getByText('Вся группа · 2 шт.')).toBeInTheDocument();
  });
  it('черновик переживает сворачивание, подсветка снимается, исходный класс остаётся виден', async () => {
    const user = userEvent.setup();
    mockApi(routes);
    setup();
    await user.click(screen.getByRole('button', { name: 'Открыть' }));
    await user.selectOptions(await screen.findByLabelText('Новый тип: 0, группа 1'), 'fence');
    expect(screen.getByText('Назначений к применению: 2')).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: 'Показать слой 0, группа 1' }).closest('tr'),
    ).toHaveTextContent('Неизвестно');
    expect(engine.current.setSemanticReview).toHaveBeenLastCalledWith({
      selected: [REVIEW.features[0]?.geometry, REVIEW.features[2]?.geometry],
      changed: [REVIEW.features[0]?.geometry, REVIEW.features[2]?.geometry],
    });
    await user.click(screen.getByRole('button', { name: 'Свернуть уточнение объектов' }));
    expect(engine.current.setSemanticReview).toHaveBeenLastCalledWith(null);
    await user.click(screen.getByRole('button', { name: 'Открыть' }));
    expect(screen.getByLabelText('Новый тип: 0, группа 1')).toHaveValue('fence');
    await user.click(screen.getByRole('button', { name: 'Отменить изменения: 0, группа 1' }));
    expect(screen.getByRole('button', { name: 'Применить и пересчитать' })).toBeDisabled();
  });
  it('применение сохраняет прежние назначения, привязку к исходнику и черновик при ошибке', async () => {
    const user = userEvent.setup();
    const calls = mockApi({
      ...routes,
      'POST /api/v1/runs/r1/review': () =>
        Response.json({ detail: 'Ошибка пересчёта' }, { status: 409 }),
    });
    setup();
    await user.click(screen.getByRole('button', { name: 'Открыть' }));
    await user.selectOptions(await screen.findByLabelText('Новый тип: 0, группа 1'), 'building');
    expect(calls.filter((c) => c.method === 'POST')).toHaveLength(0);
    await user.click(screen.getByRole('button', { name: 'Применить и пересчитать' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Ошибка пересчёта');
    const body = calls.find((c) => c.method === 'POST')?.init?.body;
    if (typeof body !== 'string') throw new Error('Нет тела запроса');
    expect(JSON.parse(body)).toEqual({
      source_sha256: 'abc123',
      feature_classes: { 'f:1': 'building', 'f:3': 'building', 'f:2': 'pole' },
      label_roles: { 'l:2': 'paved' },
    });
    expect(screen.getByLabelText('Новый тип: 0, группа 1')).toHaveValue('building');
  });
  it('штрихи оформления доступны через явный переключатель и не засоряют начальный список', async () => {
    const user = userEvent.setup();
    mockApi({
      ...routes,
      '/api/v1/runs/r1/artifacts/classification.json': {
        ...REPORT,
        groups: REPORT.groups.map((group, i) =>
          i === 2
            ? { ...group, object_class: 'ignore', evidence: { method: 'symbol_stroke:394' } }
            : group,
        ),
      },
    });
    setup();
    await user.click(screen.getByRole('button', { name: 'Открыть' }));
    await screen.findByRole('table');
    expect(screen.queryByRole('button', { name: 'Показать слой Газон, группа 3' })).toBeNull();
    await user.click(screen.getByLabelText('Показывать оформление'));
    expect(
      screen.getByRole('button', { name: 'Показать слой Газон, группа 3' }),
    ).toBeInTheDocument();
  });

  it('разные исходники блокируют назначения и подсветку', async () => {
    const user = userEvent.setup();
    mockApi({
      ...routes,
      '/api/v1/runs/r1/artifacts/classification.json': { ...REPORT, source_sha256: 'other' },
    });
    setup();
    await user.click(screen.getByRole('button', { name: 'Открыть' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('разным исходникам');
    expect(screen.queryByRole('table')).toBeNull();
    await waitFor(() => {
      expect(engine.current.setSemanticReview).toHaveBeenLastCalledWith(null);
    });
  });
});
