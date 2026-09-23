import { describe, expect, it } from 'vitest';

import { keyNotices } from './warnings';

describe('предупреждения, меняющие смысл плана', () => {
  it('выносятся в сводку, уточняющие остаются в списке', () => {
    const warnings = [
      'Граница работ не найдена: размещение идёт по всему чертежу.',
      'Профиль отключает правила: R-GASZONE-TREE-001.',
      'Склейка: габариты x.dxf и основы перекрываются на 40%',
      'В чертеже нет подземных сетей: нормы до сетей не проверены.',
    ];
    expect(keyNotices(warnings)).toEqual([warnings[0], warnings[2], warnings[3]]);
    expect(keyNotices([])).toEqual([]);
  });
});
