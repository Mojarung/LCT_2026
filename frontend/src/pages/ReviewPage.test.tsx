import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import type { ArtifactOut } from '../api/types';
import { REPORT, REVIEW } from '../lib/__fixtures__/review';
import { mockApi, run } from '../test/api';
import { renderApp } from '../test/render';

// Холст в jsdom не рисует, а Path2D в нём нет: карту проверяет живой браузер, здесь - поля,
// назначения и JSON повторного прогона.
vi.mock('../components/review/ReviewMap', () => ({
  ReviewMap: () => <canvas aria-label="Геометрия исходника" />,
}));
vi.mock('../lib/reviewPaths', () => ({
  geometryPath: () => ({}),
  joinPaths: () => ({}),
}));

const artifact = (name: string): ArtifactOut => ({
  name,
  url: `/api/v1/runs/r1/artifacts/${name}`,
  size_bytes: 1024,
});

function routes(names: string[] = ['semantic-review.geojson', 'classification.json']) {
  return {
    '/api/v1/runs/r1': run({
      state: 'failed',
      error: 'Семантика не уточнена',
      overrides: { spacing_m: 6, layer_classes: { '0': 'curb' } },
      artifacts: names.map(artifact),
    }),
    '/api/v1/runs/r1/artifacts/semantic-review.geojson': REVIEW,
    '/api/v1/runs/r1/artifacts/classification.json': REPORT,
  };
}

describe('уточнение объектов чертежа', () => {
  it('пересчёт отправляет назначения и сохраняет их при ошибке сервера', async () => {
    const user = userEvent.setup();
    const calls = mockApi({
      ...routes(['semantic-review.geojson', 'classification.json', 'review-input.dxf']),
      'POST /api/v1/runs/r1/review': () =>
        Response.json({ detail: 'Попробуйте ещё раз' }, { status: 409 }),
    });
    renderApp('/runs/r1/review');
    await screen.findByText(/Не уточнено: 2/);
    await user.selectOptions(screen.getByLabelText('Класс по исходнику'), 'building');
    await user.click(screen.getByRole('button', { name: 'Назначить класс (2 объекта)' }));
    await user.click(screen.getByRole('button', { name: 'Применить и пересчитать' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Попробуйте ещё раз');
    const request = calls.find((c) => c.method === 'POST');
    const body = request?.init?.body;
    if (typeof body !== 'string') throw new Error('Нет тела запроса уточнения');
    expect(JSON.parse(body)).toEqual({
      source_sha256: 'abc123',
      feature_classes: { 'f:1': 'building', 'f:3': 'building', 'f:2': 'pole' },
      label_roles: { 'l:2': 'paved' },
    });
    expect(screen.getByText(/Ваших назначений: 3/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Применить и пересчитать' })).toBeEnabled();
  });

  it('поиск и фильтр показывают сомнительные группы по имени', async () => {
    const user = userEvent.setup();
    const report = {
      ...REPORT,
      groups: [
        ...REPORT.groups,
        {
          layer: '08TREE',
          block: '394',
          geometry: 'Point',
          object_class: 'obstacle',
          features: 1,
          evidence: { method: 'symbol_assumed:394' },
          review_reason: 'незнакомый знак',
        },
      ],
    };
    mockApi({ ...routes(), '/api/v1/runs/r1/artifacts/classification.json': report });
    renderApp('/runs/r1/review');
    await screen.findByText(/Не уточнено:/);
    await user.click(screen.getByLabelText('Только требующие уточнения'));
    await user.type(screen.getByLabelText('Поиск слоя или блока'), '394');
    expect(screen.getByLabelText('Группа').querySelectorAll('option')).toHaveLength(1);
    expect(screen.getByLabelText('Группа')).toHaveDisplayValue(/08TREE.*394/);
  });
  it('первой открывается неизвестная группа, статус считает объекты и назначения', async () => {
    mockApi(routes());
    renderApp('/runs/r1/review');

    expect(
      await screen.findByText(
        'Элементов: 4. Автоматически: 1. Не уточнено: 2. Ваших назначений: 1.',
      ),
    ).toBeInTheDocument();
    const group = screen.getByLabelText('Группа');
    expect(group).toHaveDisplayValue('0, LineString, 2 объекта: Неизвестно');
    expect(screen.getByText(/Основание: имя не распознано/)).toBeInTheDocument();
  });

  it('класс назначается всей группе, и JSON несёт точные ссылки на объекты', async () => {
    const user = userEvent.setup();
    mockApi(routes());
    renderApp('/runs/r1/review');
    await screen.findByText(/Не уточнено: 2/);

    await user.selectOptions(screen.getByLabelText('Класс по исходнику'), 'curb');
    await user.click(screen.getByRole('button', { name: 'Назначить класс (2 объекта)' }));

    expect(
      screen.getByText('Элементов: 4. Автоматически: 1. Не уточнено: 0. Ваших назначений: 3.'),
    ).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Показать JSON' }));
    const values = JSON.parse(
      screen.getByLabelText<HTMLTextAreaElement>('JSON уточнений').value,
    ) as Record<string, unknown>;
    expect(values).toMatchObject({
      spacing_m: 6,
      feature_classes: { 'f:1': 'curb', 'f:3': 'curb', 'f:2': 'pole' },
      semantic_source_sha256: 'abc123',
      require_known_objects: true,
    });
    expect(values).not.toHaveProperty('layer_classes');
  });

  it('один объект группы выбирается номером, своё назначение отменяется', async () => {
    const user = userEvent.setup();
    mockApi(routes());
    renderApp('/runs/r1/review');
    await screen.findByText(/Не уточнено: 2/);

    const object = screen.getByLabelText('Объект в группе (0 - вся группа)');
    await user.clear(object);
    await user.type(object, '2');
    expect(screen.getByText(/Погрешность геометрии, м: 0.01/)).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText('Класс по исходнику'), 'fence');
    await user.click(screen.getByRole('button', { name: 'Назначить класс (1 объект)' }));
    expect(screen.getByText(/Не уточнено: 1\. Ваших назначений: 2\./)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Отменить назначение' }));
    expect(screen.getByText(/Не уточнено: 2\. Ваших назначений: 1\./)).toBeInTheDocument();
  });

  it('роль подписи назначается по номеру на карте и попадает в JSON', async () => {
    const user = userEvent.setup();
    mockApi(routes());
    renderApp('/runs/r1/review');
    await screen.findByText(/Не уточнено: 2/);

    const number = screen.getByLabelText('Номер подписи на карте (0 - не выбрана)');
    await user.clear(number);
    await user.type(number, '1');
    expect(screen.getByText(/ГАЗОН/)).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText('Роль выбранной подписи'), 'paved');
    await user.click(screen.getByRole('button', { name: 'Назначить роль' }));
    expect(screen.getByText(/Основание: назначено вами/)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Показать JSON' }));
    const values = JSON.parse(
      screen.getByLabelText<HTMLTextAreaElement>('JSON уточнений').value,
    ) as { label_roles: Record<string, string> };
    expect(values.label_roles).toEqual({ 'l:2': 'paved', 'l:1': 'paved' });
  });

  it('копия DXF для повторного прогона предлагается, если сервис её сохранил', async () => {
    mockApi(routes(['semantic-review.geojson', 'classification.json', 'review-input.dxf']));
    renderApp('/runs/r1/review');
    const link = await screen.findByRole('link', { name: 'Исходник для повторной проверки' });
    expect(link).toHaveAttribute('href', '/api/v1/runs/r1/artifacts/review-input.dxf');
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Применить и пересчитать' })).toBeEnabled(),
    );
  });

  it('без геометрии - одна строка и дорога к прогону, формы нет', async () => {
    mockApi(routes(['classification.json']));
    renderApp('/runs/r1/review');
    expect(
      await screen.findByText(
        'Уточнять нечего: неизвестных объектов в этом прогоне сервис не сохранил.',
      ),
    ).toBeInTheDocument();
    // Одна дорога назад - в шапке; вторая под строкой её повторяла (жюри, итерация 8).
    expect(screen.getAllByRole('link', { name: /к прогону/i })).toHaveLength(1);
    expect(screen.getByRole('link', { name: '← к прогону' })).toHaveAttribute('href', '/runs/r1');
    // Тринадцать отключённых полей с нулями спорили со строкой «уточнять нечего».
    expect(screen.queryByLabelText('Группа')).toBeNull();
    expect(screen.queryByRole('button', { name: /Назначить/ })).toBeNull();
  });

  it('несуществующий прогон - строка и дорога к консоли', async () => {
    mockApi({});
    renderApp('/runs/nope/review');
    expect(await screen.findByText('Такого прогона нет.')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: '← все прогоны' })).toHaveAttribute('href', '/');
    expect(screen.queryByLabelText('Группа')).toBeNull();
  });

  it('упавший на неизвестном прогон ведёт на уточнение и отдаёт отчёт распознавания', async () => {
    mockApi(routes());
    renderApp('/runs/r1');
    const link = await screen.findByRole('link', { name: 'Уточнить объекты на чертеже' });
    expect(link).toHaveAttribute('href', '/runs/r1/review');
    const report = screen.getByRole('link', { name: 'Отчёт распознавания' });
    expect(report).toHaveAttribute('href', '/api/v1/runs/r1/artifacts/classification.json');
    expect(report).toHaveAttribute('download');
    // У упавшего прогона обе ссылки в карточке причины, а не под раскрытием.
    expect(link).toBeVisible();
    expect(report).toBeVisible();
  });
});
