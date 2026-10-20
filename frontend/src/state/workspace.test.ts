import { describe, expect, it, vi } from 'vitest';

import { MAP_STYLE_KEY } from '../map/style';
import { DEFAULT_LAYERS } from '../map/types';
import { resetWorkspace, useWorkspace } from './workspace';

const state = () => useWorkspace.getState();

describe('рабочее место прогона', () => {
  it('новый прогон сбрасывает выбор и фильтры, тот же прогон - нет', () => {
    state().enter('r1');
    state().setLayer('lawns', false);
    state().toggleSpecies('tilia_cordata', false);
    state().enter('r1');
    expect(state().layers.lawns).toBe(false);
    state().enter('r2');
    expect(state().runId).toBe('r2');
    expect(state().layers).toEqual(DEFAULT_LAYERS);
    expect(state().speciesOff.size).toBe(0);
  });

  it('виды скрываются и показываются по одному и все разом', () => {
    state().toggleSpecies('tilia_cordata', false);
    state().toggleSpecies('acer_platanoides', false);
    expect([...state().speciesOff]).toEqual(['tilia_cordata', 'acer_platanoides']);
    state().toggleSpecies('tilia_cordata', true);
    expect([...state().speciesOff]).toEqual(['acer_platanoides']);
    state().showAllSpecies();
    expect(state().speciesOff.size).toBe(0);
  });

  it('подсветка вида - переключатель: второй щелчок снимает её', () => {
    state().toggleHighlight('tilia_cordata');
    expect(state().highlight).toBe('tilia_cordata');
    state().toggleHighlight('acer_platanoides');
    expect(state().highlight).toBe('acer_platanoides');
    state().toggleHighlight('acer_platanoides');
    expect(state().highlight).toBeNull();
  });

  it('режим правки подсказывает, как двигать посадку, выход - стирает подсказку', () => {
    state().setEditing(true);
    expect(state().message.text).toMatch(/Alt\+стрелки/);
    state().setEditing(false);
    expect(state().message).toEqual({ text: '', kind: 'info' });
  });

  it('сообщение об ошибке помечается видом', () => {
    state().say('Сервис не ответил', 'error');
    expect(state().message).toEqual({ text: 'Сервис не ответил', kind: 'error' });
    state().say('Готово');
    expect(state().message.kind).toBe('info');
  });

  it('свёрнутые панели и легенда переживают перезагрузку', () => {
    state().togglePanel('left');
    state().setLegend(true);
    expect(localStorage.getItem('green-panel-left')).toBe('1');
    expect(localStorage.getItem('green-legend')).toBe('1');
    resetWorkspace();
    expect(state().panels).toEqual({ left: true, right: false, legend: true });
    state().togglePanel('left');
    expect(localStorage.getItem('green-panel-left')).toBe('0');
  });

  it('стиль карты пишется в хранилище и атрибутом на html', () => {
    state().setMapStyle('illustrated');
    expect(localStorage.getItem(MAP_STYLE_KEY)).toBe('illustrated');
    expect(document.documentElement.dataset.mapStyle).toBe('illustrated');
    expect(state().mapStyle).toBe('illustrated');
  });

  it('без хранилища браузера панели развёрнуты, а переключение не падает', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('SecurityError');
    });
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('SecurityError');
    });
    resetWorkspace();
    expect(state().panels).toEqual({ left: false, right: false, legend: false });
    state().togglePanel('right');
    expect(state().panels.right).toBe(true);
  });

  it('счётчик правок, масштаб, ориентация, перенос и устаревание - простые поля', () => {
    state().touch();
    state().touch();
    state().setZoomShare(0.8);
    state().setOrientation('north');
    state().setPlacing(true);
    state().setStale(true);
    expect(state()).toMatchObject({
      revision: 2,
      zoomShare: 0.8,
      orientation: 'north',
      placing: true,
      stale: true,
    });
  });
});
