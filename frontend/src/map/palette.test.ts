import { describe, expect, it, vi } from 'vitest';

import { Palette, STYLES, VERDICT_TOKEN } from './palette';

function rootWith(vars: Record<string, string>): HTMLElement {
  const root = document.createElement('div');
  for (const [name, value] of Object.entries(vars)) root.style.setProperty(name, value);
  document.body.append(root);
  return root;
}

describe('цвета карты из CSS-переменных', () => {
  it('берёт значение переменной без пробелов, неизвестная - серый запасной', () => {
    const palette = new Palette(rootWith({ '--ok': '  #2f7d32 ' }));
    expect(palette.get('--ok')).toBe('#2f7d32');
    expect(palette.get('--missing')).toBe('#888');
  });

  it('кэширует цвет до clear: смена темы видна только после сброса', () => {
    const root = rootWith({ '--accent': 'red' });
    const palette = new Palette(root);
    const computed = vi.spyOn(window, 'getComputedStyle');
    expect(palette.get('--accent')).toBe('red');
    root.style.setProperty('--accent', 'blue');
    expect(palette.get('--accent')).toBe('red');
    expect(computed).toHaveBeenCalledTimes(1);
    palette.clear();
    expect(palette.get('--accent')).toBe('blue');
    expect(computed).toHaveBeenCalledTimes(2);
  });

  it('по умолчанию читает переменные корня документа', () => {
    document.documentElement.style.setProperty('--grid', '#ddd');
    expect(new Palette().get('--grid')).toBe('#ddd');
    document.documentElement.style.removeProperty('--grid');
  });
});

describe('стили классов и вердиктов', () => {
  it('запрет и отказ одного цвета, согласование - предупреждение', () => {
    expect(VERDICT_TOKEN.rejected).toBe(VERDICT_TOKEN.forbidden);
    expect(VERDICT_TOKEN.needs_approval).toBe('--warn');
  });

  it('каждый класс виден: заливкой или обводкой ненулевой толщины', () => {
    const invisible = Object.entries(STYLES)
      .filter(([, style]) => !style.fill && !(style.stroke && style.width > 0))
      .map(([cls]) => cls);
    expect(invisible).toEqual([]);
  });
});
