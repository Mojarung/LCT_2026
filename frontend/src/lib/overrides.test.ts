import { describe, expect, it } from 'vitest';

import { diffOverrides, formDefaults, type ProfileParams } from './overrides';

const strict: ProfileParams = {
  name: 'strict',
  planting_type: 'tree',
  spacing_m: 5,
  modes: ['alley', 'lawn', 'fill'],
  root_barriers: false,
  shrub_groups: true,
  shrub_rows: true,
  curb_hedges: true,
  understory: true,
  shrub_fill: true,
};
const shrubs: ProfileParams = {
  ...strict,
  name: 'shrubs',
  planting_type: 'shrub',
  spacing_m: 1,
  modes: ['alley', 'lawn'],
};

describe('параметры поверх профиля', () => {
  it('нетронутая форма ничего не шлёт: работает профиль как есть', () => {
    expect(diffOverrides(strict, formDefaults(strict), '')).toEqual({});
    // Находка аудита: форма слала шаг 5 м и добор зоны поверх профиля кустарника.
    expect(diffOverrides(shrubs, formDefaults(shrubs), '')).toEqual({});
  });

  it('шлёт ровно то, что изменил человек', () => {
    const form = formDefaults(strict);
    expect(diffOverrides(strict, { ...form, spacing_m: 6 }, '')).toEqual({ spacing_m: 6 });
    expect(diffOverrides(strict, { ...form, fill: false }, '')).toEqual({
      modes: ['alley', 'lawn'],
    });
    expect(
      diffOverrides(strict, { ...form, switches: { ...form.switches, root_barriers: true } }, ''),
    ).toEqual({ root_barriers: true });
    expect(
      diffOverrides(strict, { ...form, switches: { ...form.switches, shrub_fill: false } }, ''),
    ).toEqual({ shrub_fill: false });
    expect(diffOverrides(shrubs, { ...formDefaults(shrubs), fill: true }, '')).toEqual({
      modes: ['alley', 'lawn', 'fill'],
    });
  });

  it('JSON поверх профиля сохраняется, и приёмы из него главнее галочки добора', () => {
    const form = formDefaults(strict);
    expect(diffOverrides(strict, form, '{"species_code": "acer_platanoides"}')).toEqual({
      species_code: 'acer_platanoides',
    });
    expect(diffOverrides(strict, { ...form, fill: false }, '{"modes": ["alley"]}')).toEqual({
      modes: ['alley'],
    });
  });

  it('битый JSON и не объект - ошибка с понятной причиной', () => {
    const form = formDefaults(strict);
    expect(() => diffOverrides(strict, form, '{не json')).toThrow(/некорректный JSON/);
    expect(() => diffOverrides(strict, form, '[1, 2]')).toThrow(/JSON-объект/);
  });
});
