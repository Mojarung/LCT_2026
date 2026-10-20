import { act, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';

import { PlanEditor, type RebuildPhase } from '../../state/editor';
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

  it('says the rebuild waits in the queue, then that it runs, without promising a minute', async () => {
    let report: (phase: RebuildPhase) => void = () => undefined;
    let finish: () => void = () => undefined;
    const editor = {
      rebuild: (onPhase?: (phase: RebuildPhase) => void) => {
        report = onPhase ?? report;
        return new Promise<void>((resolve) => {
          finish = resolve;
        });
      },
    } as unknown as PlanEditor;
    const user = userEvent.setup();
    render(<EditBar editor={editor} onRebuilt={() => undefined} />);
    act(() => {
      useWorkspace.getState().setStale(true);
    });

    await user.click(screen.getByRole('button', { name: 'Пересобрать DXF' }));
    expect(screen.getByRole('status')).toHaveTextContent('Пересобираем DXF и объяснения…');
    expect(screen.getByRole('status')).not.toHaveTextContent('до минуты');
    act(() => {
      report('queued');
    });
    expect(screen.getByRole('status')).toHaveTextContent(
      'Пересборка в очереди: сервис считает другие прогоны.',
    );
    expect(screen.getByRole('button', { name: 'В очереди…' })).toBeDisabled();
    act(() => {
      report('running');
    });
    expect(screen.getByRole('status')).toHaveTextContent('Пересобираем DXF и объяснения…');
    expect(screen.getByRole('button', { name: 'Пересобираем…' })).toBeDisabled();
    await act(async () => {
      finish();
      await Promise.resolve();
    });
    expect(screen.getByRole('status')).toHaveTextContent('Файлы результата пересобраны');
    expect(useWorkspace.getState().stale).toBe(false);
  });
});
