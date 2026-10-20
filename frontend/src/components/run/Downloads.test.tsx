import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { describe, expect, it, vi } from 'vitest';

import type { ArtifactOut } from '../../api/types';
import { Downloads } from './Downloads';

const file = (name: string, size_bytes: number | null = 2048): ArtifactOut => ({
  name,
  size_bytes,
  url: `/api/v1/runs/r1/artifacts/${name}`,
});

function view(props: Partial<Parameters<typeof Downloads>[0]> = {}) {
  const router = createMemoryRouter(
    [
      {
        path: '/runs/:runId',
        element: <Downloads runId="r1" artifacts={[]} {...props} />,
      },
      { path: '/runs/:runId/review', element: <p>Проверка распознавания</p> },
    ],
    { initialEntries: ['/runs/r1'] },
  );
  return render(<RouterProvider router={router} />);
}

describe('выгрузка прогона', () => {
  it('без файлов ничего не показывает', () => {
    const { container } = view();
    expect(container).toBeEmptyDOMElement();
  });

  it('только DXF - одна кнопка, без окна файлов', () => {
    view({ artifacts: [file('result.dxf', null)] });
    const link = screen.getByRole('link', { name: /Скачать план/ });
    expect(link).toHaveAttribute('href', '/api/v1/runs/r1/artifacts/result.dxf');
    expect(link).toHaveAttribute('download');
    expect(screen.queryByRole('button', { name: /Отчёты и другие файлы/ })).not.toBeInTheDocument();
  });

  it('окно файлов: главные, служебные, журнал чтения; проверка распознавания', async () => {
    const user = userEvent.setup();
    const onReview = vi.fn();
    view({
      artifacts: [
        file('result.dxf'),
        file('report.html'),
        file('interpretations.csv'),
        file('semantic-review.geojson'),
        file('plan.json', 1_500_000),
      ],
      notes: ['Блок без определения: 2 вставки'],
      onReview,
    });
    await user.click(screen.getByRole('button', { name: /Отчёты и другие файлы/ }));
    const dialog = screen.getByRole('dialog', { name: 'Отчёты и файлы прогона' });
    expect(within(dialog).getByRole('link', { name: /Отчёт по посадкам/ })).toHaveAttribute(
      'target',
      '_blank',
    );
    expect(within(dialog).getByRole('link', { name: /Нормы · CSV/ })).toHaveAttribute('download');
    expect(within(dialog).getByText('Файлы расчёта · 2')).toBeInTheDocument();
    expect(within(dialog).getByRole('link', { name: /plan\.json/ })).toBeInTheDocument();
    expect(within(dialog).getByText('Чтение чертежа · 1')).toBeInTheDocument();
    expect(within(dialog).getByText('Блок без определения: 2 вставки')).toBeInTheDocument();
    await user.click(
      within(dialog).getByRole('button', { name: 'Проверить распознавание объектов' }),
    );
    expect(onReview).toHaveBeenCalled();
  });

  it('без обработчика проверка распознавания - ссылка на страницу проверки', async () => {
    const user = userEvent.setup();
    view({ artifacts: [file('semantic-review.geojson')] });
    await user.click(screen.getByRole('button', { name: /Отчёты и другие файлы/ }));
    await user.click(screen.getByRole('link', { name: 'Проверить распознавание объектов' }));
    expect(await screen.findByText('Проверка распознавания')).toBeInTheDocument();
  });

  it('окно закрывается кнопкой', async () => {
    const user = userEvent.setup();
    view({ artifacts: [file('result.dxf')], notes: ['заметка'] });
    await user.click(screen.getByRole('button', { name: /Отчёты и другие файлы/ }));
    const dialog = screen.getByRole('dialog', { name: 'Отчёты и файлы прогона' });
    await user.click(
      within(dialog).getByRole('button', { name: 'Закрыть: Отчёты и файлы прогона' }),
    );
    await waitFor(() => {
      expect(dialog).not.toHaveAttribute('open');
    });
  });
});
