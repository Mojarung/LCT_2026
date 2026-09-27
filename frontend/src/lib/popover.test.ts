import { describe, expect, it } from 'vitest';

import { placeNear } from './popover';

const size = { width: 300, height: 200 };
const area = { width: 1440, height: 900 };

describe('карточка у точки на карте', () => {
  it('по умолчанию справа снизу от точки', () => {
    expect(placeNear(400, 300, size, area)).toEqual({ left: 412, top: 312 });
  });

  it('у правого края открывается влево, у нижнего - вверх', () => {
    expect(placeNear(1300, 300, size, area)).toEqual({ left: 988, top: 312 });
    expect(placeNear(400, 850, size, area)).toEqual({ left: 412, top: 638 });
  });

  it('не ложится на панель, если с другой стороны точки есть место', () => {
    const panel = { left: 1072, top: 70, width: 356, height: 780 };
    expect(placeNear(960, 420, size, area, [panel])).toEqual({ left: 648, top: 432 });
  });

  it('если места нет нигде, прижимается к краям карты', () => {
    const tiny = { width: 200, height: 150 };
    const placed = placeNear(100, 100, size, tiny);
    expect(placed.left).toBeGreaterThanOrEqual(8);
    expect(placed.top).toBeGreaterThanOrEqual(8);
  });
});
