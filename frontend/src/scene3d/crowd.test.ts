import { describe, expect, it } from 'vitest';

import { Walls } from './collide';
import { personGeometry, placePeople } from './people';
import { benchBack } from './streetDetails';

function frame(width: number, height: number, m = 0.5) {
  return { width, height, metresPerPx: m, rect: [0, 0, width * m, height * m] as const };
}

describe('люди не ходят сквозь ограду и по газону', () => {
  it('путь гуляющего - целиком по разрешённым клеткам', () => {
    // Тротуар 40 x 6 м (код 1), посередине поперёк - ограда (клетки не разрешены), вокруг газон.
    const f = frame(100, 30);
    const kinds = new Uint8Array(f.width * f.height);
    for (let y = 12; y < 24; y++) {
      for (let x = 10; x < 90; x++) kinds[y * f.width + x] = x === 50 ? 0 : 1;
    }
    const grid = { ...f, rect: [...f.rect] as [number, number, number, number], kinds };
    const people = placePeople(grid, 40, 7, { allowed: [1] });
    expect(people.length).toBeGreaterThan(5);
    const at = (x: number, z: number) => kinds[Math.floor(z / 0.5) * f.width + Math.floor(x / 0.5)];
    for (const p of people) {
      const dx = Math.sin(p.heading);
      const dz = Math.cos(p.heading);
      for (let t = -0.5; t <= 0.5; t += 0.05) {
        expect(at(p.x + dx * p.span * t, p.z + dz * p.span * t)).toBe(1);
      }
    }
  });

  it('клетки у ограды и внутри скамейки заняты, вдали - свободны', () => {
    const walls = new Walls([]);
    walls.addLines(
      [
        {
          points: [
            { x: 5, z: 1 },
            { x: 5, z: 9 },
          ],
        },
      ],
      1.2,
    );
    walls.addRings(
      [
        [
          { x: 12, z: 4 },
          { x: 13.8, z: 4 },
          { x: 13.8, z: 4.6 },
          { x: 12, z: 4.6 },
        ],
      ],
      0.9,
    );
    const f = frame(40, 20);
    const blocked = walls.blockedCells(f, 0.4);
    const cell = (x: number, z: number) =>
      blocked[Math.floor(z / 0.5) * f.width + Math.floor(x / 0.5)];
    expect(cell(5.1, 5)).toBe(1);
    expect(cell(5.4, 5)).toBe(1);
    expect(cell(12.9, 4.3)).toBe(1);
    expect(cell(8, 5)).toBe(0);
    expect(cell(16, 8)).toBe(0);
  });

  it('ребёнок ниже взрослого', () => {
    const top = (child: boolean) => {
      const pos = personGeometry(child).getAttribute('position');
      let y = 0;
      for (let i = 0; i < pos.count; i++) y = Math.max(y, pos.getY(i));
      return y;
    };
    expect(top(false)).toBeGreaterThan(1.7);
    expect(top(true)).toBeLessThan(1.25);
    expect(top(true)).toBeGreaterThan(1.0);
  });
});

describe('спинка скамейки - только у ограды', () => {
  const fence = {
    points: [
      { x: 0, z: 0 },
      { x: 10, z: 0 },
    ],
  };

  it('ограда за скамейкой - спинка, сиденьем от ограды', () => {
    // Скамейка вдоль ограды в 0,8 м, смотрит на ограду: разворачивается к ней спиной.
    const r = benchBack({ x: 5, z: 0.8, angle: Math.PI }, [fence]);
    expect(r.back).toBe(true);
    expect(Math.sin(r.angle)).toBeCloseTo(0, 6);
    expect(Math.cos(r.angle)).toBeCloseTo(1, 6);
  });

  it('без ограды рядом и у поперечной ограды - без спинки', () => {
    expect(benchBack({ x: 5, z: 3, angle: 0 }, [fence]).back).toBe(false);
    const across = {
      points: [
        { x: 6, z: -5 },
        { x: 6, z: 5 },
      ],
    };
    expect(benchBack({ x: 5, z: 0.5, angle: 0 }, [across]).back).toBe(false);
  });
});
