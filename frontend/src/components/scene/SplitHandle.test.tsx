import { fireEvent, render, screen } from '@testing-library/react';
import { createRef } from 'react';
import { describe, expect, it, vi } from 'vitest';

import { clampSplit } from '../../lib/split';
import { SplitHandle } from './SplitHandle';

describe('SplitHandle', () => {
  it('keeps the plan between 20 and 80 percent', () => {
    expect(clampSplit(0.05)).toBe(0.2);
    expect(clampSplit(0.95)).toBe(0.8);
    expect(clampSplit(0.4)).toBe(0.4);
  });

  it('moves with arrow keys and resets on double click', () => {
    const onChange = vi.fn();
    render(<SplitHandle host={createRef()} value={0.5} onChange={onChange} />);
    const handle = screen.getByRole('button', { name: /Высота схемы участка: 50/ });
    fireEvent.keyDown(handle, { key: 'ArrowUp' });
    expect(onChange).toHaveBeenLastCalledWith(0.55);
    fireEvent.keyDown(handle, { key: 'ArrowDown' });
    expect(onChange).toHaveBeenLastCalledWith(0.45);
    fireEvent.doubleClick(handle);
    expect(onChange).toHaveBeenLastCalledWith(0.5);
  });
});
