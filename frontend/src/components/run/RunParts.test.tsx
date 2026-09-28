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

describe('RunMetrics', () => {
  it('называет деревья и кустарники, когда план загружен целиком', () => {
    // Жюри по дизайну (итерация 9): «994 посадки» не отвечали, сколько деревьев.
    show({ trees: 205, planted: 994 });
    expect(
      screen.getByText(/посадки в плане: 205 деревьев, 789 кустарников, 28 на согласование/),
    ).toBeInTheDocument();
  });

  it('молчит о составе, пока план не сходится с числом прогона', () => {
    show({ trees: 3, planted: 3 });
    expect(screen.queryByText(/деревьев|деревья|дерево/)).toBeNull();
  });
});
