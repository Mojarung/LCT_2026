import { act, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';

import { EngineContext } from '../../state/engine';
import { useWorkspace } from '../../state/workspace';
import { Legend } from './Legend';
import { MapHud } from './MapHud';

function hud() {
  return render(
    <EngineContext.Provider value={{ current: null }}>
      <MapHud />
    </EngineContext.Provider>,
  );
}

describe('стиль карты', () => {
  it('по умолчанию чертёж; «кроны» переключают на иллюстрацию и запоминают выбор', async () => {
    hud();
    const drawing = screen.getByRole('button', { name: 'чертёж' });
    const crowns = screen.getByRole('button', { name: 'кроны' });
    expect(drawing).toHaveAttribute('aria-pressed', 'true');
    expect(crowns).toHaveAttribute('aria-pressed', 'false');

    await userEvent.click(crowns);

    expect(crowns).toHaveAttribute('aria-pressed', 'true');
    expect(drawing).toHaveAttribute('aria-pressed', 'false');
    expect(useWorkspace.getState().mapStyle).toBe('illustrated');
    expect(localStorage.getItem('green-map-style')).toBe('illustrated');
    // По атрибуту CSS меняет токены подосновы, а движок перерисовывает карту.
    expect(document.documentElement.dataset.mapStyle).toBe('illustrated');

    await userEvent.click(drawing);
    expect(document.documentElement.dataset.mapStyle).toBe('engineering');
  });

  it('смена прогона стиль не сбрасывает', () => {
    act(() => {
      useWorkspace.getState().setMapStyle('illustrated');
      useWorkspace.getState().enter('другой-прогон');
    });
    expect(useWorkspace.getState().mapStyle).toBe('illustrated');
  });

  it('легенда чертежа - знаки и формулировки проектировщиков, иллюстрации - модели', () => {
    act(() => {
      useWorkspace.getState().setLegend(true);
    });
    const { unmount } = render(<Legend done />);
    expect(screen.getByText('Проектируемое дерево (место посадки, контур кроны)')).toBeVisible();
    expect(screen.getByText('Живая изгородь, ряд кустарника')).toBeVisible();
    expect(screen.getByText('Существующее хвойное насаждение')).toBeVisible();
    expect(screen.getByText('Существующая живая изгородь, ширина условная')).toBeVisible();
    expect(screen.queryByText('дерево по съёмке')).toBeNull();
    unmount();

    act(() => {
      useWorkspace.getState().setMapStyle('illustrated');
    });
    render(<Legend done />);
    expect(screen.getByText('дерево по съёмке')).toBeVisible();
    expect(screen.queryByText('Существующее хвойное насаждение')).toBeNull();
  });

  it('кнопка «править» есть только у готового плана и включает режим правки', async () => {
    const { unmount } = hud();
    expect(screen.queryByRole('button', { name: 'править' })).toBeNull();
    unmount();
    render(
      <EngineContext.Provider value={{ current: null }}>
        <MapHud editable />
      </EngineContext.Provider>,
    );
    const edit = screen.getByRole('button', { name: 'править' });
    expect(edit).toHaveAttribute('aria-pressed', 'false');
    await userEvent.click(edit);
    expect(useWorkspace.getState().editing).toBe(true);
    expect(edit).toHaveAttribute('aria-pressed', 'true');
    act(() => {
      useWorkspace.getState().setEditing(false);
    });
  });

  it('легенда по умолчанию закрыта', () => {
    localStorage.removeItem('green-legend');
    act(() => {
      useWorkspace.getState().enter('новый-прогон');
    });
    expect(useWorkspace.getState().panels.legend).toBe(false);
  });
});
