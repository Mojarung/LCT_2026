import { describe, expect, it } from 'vitest';

import {
  distanceToArea,
  furnish,
  groundKind,
  groundsOf,
  type Item,
  itemFootprint,
  playgroundGroup,
} from './playgrounds';
import type { Flat } from './types';

function rect(x0: number, z0: number, x1: number, z1: number): Flat[] {
  return [
    { x: x0, z: z0 },
    { x: x1, z: z0 },
    { x: x1, z: z1 },
    { x: x0, z: z1 },
    { x: x0, z: z0 },
  ];
}

function inside(rings: Flat[][], item: Item): boolean {
  return itemFootprint(item).ring.every((p) => distanceToArea(rings, p) === 0);
}

describe('площадки по подписям', () => {
  it('вид площадки - по подписи чертежа', () => {
    expect(groundKind('ДЕТ.ПЛ.')).toBe('kids');
    expect(groundKind('СПОРТ ПЛ.')).toBe('sports');
    expect(groundKind('СПЕЦ.ПОКР.')).toBeNull();
  });

  it('подпись на резине даёт набор, подпись вдали - нет', () => {
    const part = [rect(0, 0, 20, 12)];
    const grounds = groundsOf(
      [part],
      [
        { x: 10, z: 6, kind: 'kids' },
        { x: 11, z: 7, kind: 'kids' },
        { x: 60, z: 6, kind: 'sports' },
      ],
    );
    expect(grounds).toHaveLength(1);
    expect(grounds[0]?.kind).toBe('kids');
  });

  it('детская: качели, горка, песочница и две скамейки внутри контура, не друг на друге', () => {
    const rings = [rect(0, 0, 20, 12)];
    const items = furnish({ rings, kind: 'kids', anchor: { x: 10, z: 6 } }, []);
    const kinds = items.map((i) => i.kind).sort();
    expect(kinds).toEqual(['bench', 'bench', 'sandbox', 'slide', 'swing']);
    expect(items.every((i) => inside(rings, i))).toBe(true);
    for (const a of items) {
      for (const b of items) {
        if (a !== b) expect(Math.hypot(a.x - b.x, a.z - b.z)).toBeGreaterThan(1.5);
      }
    }
  });

  it('скамейки смотрят на середину площадки', () => {
    const rings = [rect(0, 0, 20, 12)];
    const benches = furnish({ rings, kind: 'kids', anchor: { x: 10, z: 6 } }, []).filter(
      (i) => i.kind === 'bench',
    );
    for (const b of benches) {
      const facing = { x: Math.sin(b.angle), z: Math.cos(b.angle) };
      expect(facing.x * (10 - b.x) + facing.z * (6 - b.z)).toBeGreaterThan(0);
    }
  });

  it('спортивная: ворота у торцов лицом в поле и турники', () => {
    const rings = [rect(0, 0, 30, 15)];
    const items = furnish({ rings, kind: 'sports', anchor: { x: 15, z: 7.5 } }, [], [], false);
    const goals = items.filter((i) => i.kind === 'goal');
    expect(goals).toHaveLength(2);
    for (const g of goals) {
      const facing = { x: Math.sin(g.angle), z: Math.cos(g.angle) };
      expect(facing.x * (15 - g.x) + facing.z * (7.5 - g.z)).toBeGreaterThan(0);
    }
    expect(items.some((i) => i.kind === 'bars')).toBe(true);
    expect(items.every((i) => inside(rings, i))).toBe(true);
  });

  it('дерево на месте горки - горка встаёт в стороне', () => {
    const rings = [rect(0, 0, 20, 12)];
    const items = furnish({ rings, kind: 'kids', anchor: { x: 10, z: 6 } }, [
      { x: 10, z: 6, r: 1.5 },
    ]);
    for (const i of items) expect(Math.hypot(i.x - 10, i.z - 6)).toBeGreaterThan(1.5);
  });

  it('на маленькой площадке лишнее не ставится', () => {
    const rings = [rect(0, 0, 4, 4)];
    const items = furnish({ rings, kind: 'kids', anchor: { x: 2, z: 2 } }, []);
    expect(items.every((i) => inside(rings, i))).toBe(true);
    expect(items.length).toBeLessThan(3);
  });

  it('модели собираются в группу сеток', () => {
    const group = playgroundGroup([
      { kind: 'swing', x: 0, z: 0, angle: 0 },
      { kind: 'slide', x: 5, z: 0, angle: 0 },
      { kind: 'sandbox', x: 10, z: 0, angle: 0 },
      { kind: 'goal', x: 15, z: 0, angle: 0 },
      { kind: 'bars', x: 20, z: 0, angle: 0 },
      { kind: 'bench', x: 25, z: 0, angle: 0 },
    ]);
    expect(group?.children.length).toBeGreaterThan(6);
  });
});
