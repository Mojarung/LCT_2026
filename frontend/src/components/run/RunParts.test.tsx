import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { describe, expect, it } from 'vitest';

import type { RunOut } from '../../api/types';
import { RunMetrics } from './RunParts';

const run = {
  id: 'r1',
  state: 'succeeded',
  source_name: 'улица.dxf',
  profile: 'strict',
  overrides: {},
  created_at: '',
  updated_at: '',
  error: null,
  summary: { placements: 994, needs_approval: 28, rejections: 620, integrity_ok: true },
  artifacts: {},
} as unknown as RunOut;

const show = (trees: { trees: number; planted: number } | null) =>
  render(
    <MemoryRouter>
      <RunMetrics run={run} trees={trees} />
    </MemoryRouter>,
  );

/** Значение строки разбивки «Деревья / Кустарники» по её подписи. */
const breakdown = (term: string) => screen.getByText(term, { selector: 'dt' }).nextElementSibling;

describe('RunMetrics', () => {
  it('называет деревья и кустарники, когда план загружен целиком', () => {
    // Жюри по дизайну (итерация 9): «994 посадки» не отвечали, сколько деревьев.
    const { container } = show({ trees: 205, planted: 994 });
    expect(container.querySelector('.metric')).toHaveTextContent(/^994посадки в плане$/);
    expect(breakdown('Деревья')).toHaveTextContent(/^205$/);
    expect(breakdown('Кустарники')).toHaveTextContent(/^789$/);
    expect(container.querySelector('.run-approval')).toHaveTextContent(/^На согласование 28$/);
  });

  it('молчит о составе, пока план не сходится с числом прогона', () => {
    const { container } = show({ trees: 3, planted: 3 });
    expect(container.querySelector('.run-breakdown')).toBeNull();
    expect(screen.queryByText(/деревь|кустарник/i)).toBeNull();
  });
});
