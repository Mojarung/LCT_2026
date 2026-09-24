import { act, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { PlanEditor } from '../../state/editor';
import { useWorkspace } from '../../state/workspace';
import { EditBar } from './EditBar';

const leave = (): Event => {
  const event = new Event('beforeunload', { cancelable: true });
  window.dispatchEvent(event);
  return event;
};

describe('EditBar', () => {
  it('offers the rebuild only when there are edits to rebuild', () => {
    render(<EditBar editor={new PlanEditor('r1')} onRebuilt={() => undefined} />);
    expect(screen.queryByRole('button', { name: /Пересобрать DXF/ })).toBeNull();

    act(() => {
      useWorkspace.getState().setStale(true);
    });
    expect(screen.getByRole('button', { name: /Пересобрать DXF/ })).toBeEnabled();
  });

  it('warns before leaving only while the plan is edited and the DXF is not rebuilt', () => {
    const view = render(<EditBar editor={new PlanEditor('r1')} onRebuilt={() => undefined} />);
    expect(leave().defaultPrevented).toBe(false);

    act(() => {
      useWorkspace.getState().setStale(true);
    });
    expect(leave().defaultPrevented).toBe(true);

    act(() => {
      useWorkspace.getState().setStale(false);
    });
    expect(leave().defaultPrevented).toBe(false);

    act(() => {
      useWorkspace.getState().setStale(true);
    });
    view.unmount();
    expect(leave().defaultPrevented).toBe(false);
  });
});
