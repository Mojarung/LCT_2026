import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router';
import { beforeAll, describe, expect, it, vi } from 'vitest';
import type { SourceConflicts } from '../../api/artifacts';
import { SourceConflictNotice } from './SourceConflictNotice';

beforeAll(() => {
  HTMLDialogElement.prototype.showModal = function () {
    this.setAttribute('open', '');
  };
  HTMLDialogElement.prototype.close = function () {
    this.removeAttribute('open');
  };
});

const report: SourceConflicts = {
  version: 1,
  basis: 'source',
  checked_trees: 3,
  checked_areas: 2,
  skipped_tree_features: 0,
  skipped_area_features: 0,
  boundary_tolerance_m: 0.05,
  items: [
    {
      id: 'source-one',
      x: 12,
      y: 34,
      tree_refs: ['a'],
      targets: [
        { object_class: 'sidewalk', ref: 'b', layer: 'Контур покрытия', depth_m: 2 },
        { object_class: 'sidewalk', ref: 'c', layer: 'Вторая ссылка', depth_m: 2 },
      ],
    },
  ],
};

function show(props: Partial<React.ComponentProps<typeof SourceConflictNotice>> = {}) {
  const result = render(
    <MemoryRouter>
      <SourceConflictNotice report={report} runId="r1" {...props} />
    </MemoryRouter>,
  );
  const trigger = screen.queryByRole('button', { name: /Конфликты подосновы ·/ });
  if (trigger) fireEvent.click(trigger);
  return result;
}

describe('source overlap notice', () => {
  it('explains source conflicts and focuses the exact unique location', async () => {
    const onFocus = vi.fn();
    show({ onFocus });
    const user = userEvent.setup();
    expect(screen.getByRole('dialog', { name: 'Конфликты подосновы' })).toHaveTextContent('· 1');
    await user.click(screen.getByText('Показать места · 1'));
    await user.click(screen.getByRole('button', { name: 'Место 1: тротуар' }));
    expect(onFocus).toHaveBeenCalledWith(report.items[0]);
    expect(screen.getByText(/не означает, что дерево нужно удалить/)).not.toBeVisible();
  });
  it('links from 3D to coordinates and the same marker on the plan', () => {
    show();
    expect(screen.getByRole('link', { name: 'Показать конфликты на плане' })).toHaveAttribute(
      'href',
      '/runs/r1#x=12&y=34&m=0.06&conflict=source-one',
    );
  });
  it('lets the user hide markers without hiding the warning', async () => {
    const onVisibilityChange = vi.fn();
    show({ onVisibilityChange });
    await userEvent.click(screen.getByRole('checkbox', { name: 'Отметки конфликтов на плане' }));
    expect(onVisibilityChange).toHaveBeenCalledWith(false);
    expect(screen.getByRole('dialog', { name: 'Конфликты подосновы' })).toBeVisible();
  });
  it('discloses the limitation of old saved map geometry', async () => {
    show({ report: { ...report, basis: 'saved_basemap' } });
    await userEvent.click(screen.getByText('Что проверено'));
    expect(screen.getByText(/по сохранённой подоснове/)).toBeVisible();
  });
  it.each(['checked_trees', 'checked_areas'] as const)(
    'reports missing geometry: %s',
    async (field) => {
      show({ report: { ...report, items: [], [field]: 0 } });
      await userEvent.click(screen.getByText('Проверка пересечений подосновы'));
      expect(screen.getByText(/Недостаточно распознанных/)).toBeVisible();
      expect(screen.queryByText(/пересечений со стволами не найдено/)).not.toBeInTheDocument();
    },
  );
  it('does not certify the whole source when nothing was found', async () => {
    show({ report: { ...report, items: [] } });
    expect(screen.queryByRole('dialog', { name: 'Конфликты подосновы' })).not.toBeInTheDocument();
    await userEvent.click(screen.getByText('Проверка пересечений подосновы'));
    expect(
      screen.getByText('В проверенных контурах пересечений со стволами не найдено.'),
    ).toBeVisible();
    expect(screen.getByText(/Открытые линии, кроны/)).toBeVisible();
  });
});
