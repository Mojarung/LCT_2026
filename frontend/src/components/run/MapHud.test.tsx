import { act, fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import type { PlanEngine } from '../../map/engine';
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
    const drawing = screen.getByRole('button', { name: 'Чертёж' });
    const crowns = screen.getByRole('button', { name: 'Кроны' });
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
    expect(screen.queryByRole('button', { name: 'Править' })).toBeNull();
    unmount();
    render(
      <EngineContext.Provider value={{ current: null }}>
        <MapHud editable />
      </EngineContext.Provider>,
    );
    const edit = screen.getByRole('button', { name: 'Править' });
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

describe('кнопки карты ведут движок', () => {
  function fakeEngine() {
    let orientation: 'street' | 'north' = 'street';
    return {
      fit: vi.fn(),
      zoomBy: vi.fn(),
      setZoomShare: vi.fn(),
      toggleOrientation: vi.fn(() => {
        orientation = orientation === 'street' ? 'north' : 'street';
      }),
      orientation: () => orientation,
    };
  }

  function withEngine(engine: ReturnType<typeof fakeEngine> | null) {
    const ref = { current: engine as unknown as PlanEngine | null };
    return render(
      <EngineContext.Provider value={ref}>
        <MapHud />
      </EngineContext.Provider>,
    );
  }

  it('«весь план», приближение и отдаление, ползунок масштаба', async () => {
    const engine = fakeEngine();
    withEngine(engine);
    await userEvent.click(screen.getByRole('button', { name: /Весь план/ }));
    expect(engine.fit).toHaveBeenCalledTimes(1);
    await userEvent.click(screen.getByRole('button', { name: 'Приблизить' }));
    await userEvent.click(screen.getByRole('button', { name: 'Отдалить' }));
    expect(engine.zoomBy.mock.calls).toEqual([[1.4], [1 / 1.4]]);
    const range = screen.getByRole('slider', { name: 'Масштаб карты' });
    expect(range).toHaveValue('500');
    fireEvent.change(range, { target: { value: '250' } });
    expect(engine.setZoomShare).toHaveBeenCalledWith(0.25);
  });

  it('«север вверх» разворачивает план, повторное нажатие на выбранное ничего не делает', async () => {
    const engine = fakeEngine();
    withEngine(engine);
    const north = screen.getByRole('button', { name: 'Север вверх' });
    await userEvent.click(north);
    expect(engine.toggleOrientation).toHaveBeenCalledTimes(1);
    expect(north).toHaveAttribute('aria-pressed', 'true');
    expect(useWorkspace.getState().orientation).toBe('north');
    await userEvent.click(north);
    expect(engine.toggleOrientation).toHaveBeenCalledTimes(1);
    await userEvent.click(screen.getByRole('button', { name: 'Вдоль улицы' }));
    expect(useWorkspace.getState().orientation).toBe('street');
  });

  it('без движка разворот и масштаб молчат, а не падают', async () => {
    withEngine(null);
    await userEvent.click(screen.getByRole('button', { name: 'Север вверх' }));
    expect(useWorkspace.getState().orientation).toBe('street');
    await userEvent.click(screen.getByRole('button', { name: /Весь план/ }));
  });

  it('у идущего прогона легенда открывается кнопкой у карты', async () => {
    withEngine(fakeEngine());
    const legend = screen.getByRole('button', { name: 'Легенда' });
    expect(legend).toHaveAttribute('aria-pressed', 'false');
    await userEvent.click(legend);
    expect(useWorkspace.getState().panels.legend).toBe(true);
    expect(legend).toHaveAttribute('aria-pressed', 'true');
    await userEvent.click(legend);
    expect(useWorkspace.getState().panels.legend).toBe(false);
  });
});
