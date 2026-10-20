import { render, screen } from '@testing-library/react';
import { expect, it } from 'vitest';
import { TreeClearanceNotice } from './TreeClearanceNotice';
import type { TreeClearanceConflict } from '../../scene3d/treeClearance';

it('поясняет происхождение дерева, фактический отступ и отсутствие решения о вырубке', () => {
  // Текст не должен выдавать существующее дерево за новую посадку сервиса.
  const conflict = {
    distance: 1.31,
    required: 5,
    rule: { act_short: 'СП 42', clause: 'таблица 9.1' },
  } as TreeClearanceConflict;
  render(<TreeClearanceNotice conflict={conflict} />);
  expect(screen.getByText('Недостаточный отступ до здания')).toBeInTheDocument();
  expect(screen.getByText('1,31 м')).toBeInTheDocument();
  expect(screen.getByText('5 м')).toBeInTheDocument();
  expect(screen.getByText(/уже было в исходном чертеже/)).toBeInTheDocument();
  expect(screen.getByText(/статус вырубки здесь не определён/)).toBeInTheDocument();
});
