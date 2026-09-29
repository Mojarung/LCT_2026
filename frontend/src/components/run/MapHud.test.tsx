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
  it('по умолчанию чертёж; кнопка переключает на иллюстрацию и запоминает выбор', async () => {
    hud();
    const toggle = screen.getByRole('button', { name: 'чертёж' });
    expect(toggle).toHaveAttribute('aria-pressed', 'true');

    await userEvent.click(toggle);

    const back = screen.getByRole('button', { name: 'иллюстрация' });
    expect(back).toHaveAttribute('aria-pressed', 'false');
    expect(useWorkspace.getState().mapStyle).toBe('illustrated');
    expect(localStorage.getItem('green-map-style')).toBe('illustrated');
    // По атрибуту CSS меняет токены подосновы, а движок перерисовывает карту.
    expect(document.documentElement.dataset.mapStyle).toBe('illustrated');

    await userEvent.click(back);
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

  it('легенда чертежа с видами плана - знак каждого вида, а не три общих', () => {
    act(() => {
      useWorkspace.getState().setLegend(true);
    });
    render(
      <Legend
        done
        species={[
          { code: 'tilia_cordata', name: 'Липа мелколистная', plantingType: 'tree' },
          { code: 'spiraea_japonica', name: 'Спирея японская', plantingType: 'shrub' },
          { code: 'fraxinus_excelsior', name: 'Ясень обыкновенный', plantingType: 'tree' },
        ]}
      />,
    );
    expect(screen.getByText('Липа мелколистная')).toBeVisible();
    expect(screen.getByText('Спирея японская')).toBeVisible();
    // Вид без знака в шаблоне остаётся в легенде - общим знаком дерева.
    expect(screen.getByText('Ясень обыкновенный')).toBeVisible();
    expect(screen.getByText('Живая изгородь, ряд кустарника')).toBeVisible();
    expect(screen.queryByText('Проектируемое дерево (место посадки, контур кроны)')).toBeNull();
  });
});
