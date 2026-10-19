import { describe, expect, it } from 'vitest';

import {
  distanceToArea,
  furnish,
  type Ground,
  groundKind,
  groundsOf,
  type Item,
  type ItemKind,
  itemFootprint,
  playgroundGroup,
  rectsOverlap,
  SPECS,
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

function ground(rings: Flat[][], kind: Ground['kind'], anchor: Flat): Ground {
  return { rings, kind, anchor, part: 0 };
}

function inside(rings: Flat[][], item: Item): boolean {
  return itemFootprint(item).ring.every((p) => distanceToArea(rings, p) === 0);
}

function zone(item: Item) {
  const spec = SPECS[item.kind];
  return {
    x: item.x,
    z: item.z,
    angle: item.angle,
    hu: spec.len / 2 + spec.zoneU,
    hv: spec.wid / 2 + spec.zoneV,
  };
}

const kinds = (items: Item[]) => new Set<ItemKind>(items.map((i) => i.kind));

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
    expect(grounds[0]?.part).toBe(0);
  });
});

describe('набор по площади: что влезло, то и встало', () => {
  const small = [rect(0, 0, 6, 5)];
  const medium = [rect(0, 0, 20, 12)];
  const large = [rect(0, 0, 40, 25)];
  const furnished = (rings: Flat[][]) =>
    furnish(ground(rings, 'kids', { x: 3, z: 2.5 }), [], { benches: false });

  it('на маленькой - песочница, без качелей и комплекса', () => {
    const items = furnished(small);
    expect(kinds(items).has('sandbox')).toBe(true);
    expect(kinds(items).has('swing')).toBe(false);
    expect(kinds(items).has('complex')).toBe(false);
  });

  it('на средней - комплекс с горкой и качели; на большой предметов больше', () => {
    const mid = furnished(medium);
    expect(kinds(mid).has('complex')).toBe(true);
    expect(kinds(mid).has('slide')).toBe(false);
    expect(kinds(mid).has('swing')).toBe(true);
    const big = furnished(large);
    expect(big.length).toBeGreaterThan(mid.length);
  });

  it('каждый предмет в контуре, свободные зоны не пересекаются', () => {
    for (const rings of [small, medium, large]) {
      const items = furnished(rings);
      for (const item of items) expect(inside(rings, item)).toBe(true);
      for (const a of items) {
        for (const b of items) if (a !== b) expect(rectsOverlap(zone(a), zone(b))).toBe(false);
      }
    }
  });

  it('дерево не попадает в свободную зону предмета', () => {
    const tree = { x: 10, z: 6, r: 1.0 };
    const items = furnish(ground(medium, 'kids', { x: 10, z: 6 }), [tree], { benches: false });
    expect(items.length).toBeGreaterThan(0);
    for (const item of items) {
      const z = zone(item);
      const c = Math.cos(z.angle);
      const s = Math.sin(z.angle);
      const u = (tree.x - z.x) * c - (tree.z - z.z) * s;
      const w = (tree.x - z.x) * s + (tree.z - z.z) * c;
      const du = Math.max(0, Math.abs(u) - z.hu);
      const dv = Math.max(0, Math.abs(w) - z.hv);
      expect(Math.hypot(du, dv)).toBeGreaterThanOrEqual(tree.r - 1e-6);
    }
  });

  it('ограда поперёк резины - предметы по обе стороны, не на ней', () => {
    const fence = Array.from({ length: 25 }, (_, k) => ({ x: 10, z: k * 0.5, r: 0.3 }));
    const items = furnish(ground(medium, 'kids', { x: 10, z: 6 }), fence, { benches: false });
    expect(items.length).toBeGreaterThan(1);
    for (const item of items) {
      const z = zone(item);
      const c = Math.cos(z.angle);
      const s = Math.sin(z.angle);
      for (const post of fence) {
        const u = (post.x - z.x) * c - (post.z - z.z) * s;
        const w = (post.x - z.x) * s + (post.z - z.z) * c;
        const gap = Math.hypot(Math.max(0, Math.abs(u) - z.hu), Math.max(0, Math.abs(w) - z.hv));
        expect(gap).toBeGreaterThanOrEqual(post.r - 1e-6);
      }
    }
  });

  it('скамейки спинкой к краю, сиденьем к середине, рядом урна', () => {
    const items = furnish(ground(medium, 'kids', { x: 10, z: 6 }), []);
    const benches = items.filter((i) => i.kind === 'bench');
    expect(benches.length).toBeGreaterThanOrEqual(2);
    for (const b of benches) {
      const facing = { x: Math.sin(b.angle), z: Math.cos(b.angle) };
      expect(facing.x * (10 - b.x) + facing.z * (6 - b.z)).toBeGreaterThan(0);
      const edge = Math.min(b.x, 20 - b.x, b.z, 12 - b.z);
      expect(edge).toBeLessThan(1.6);
    }
    const bins = items.filter((i) => i.kind === 'bin');
    expect(bins.length).toBeGreaterThan(0);
    for (const bin of bins) {
      expect(Math.min(...benches.map((b) => Math.hypot(b.x - bin.x, b.z - bin.z)))).toBeLessThan(
        1.6,
      );
    }
  });

  it('две подписи на одной резине делят её: каждый набор у своей подписи', () => {
    const part = [rect(0, 0, 44, 12)];
    const grounds = groundsOf(
      [part],
      [
        { x: 8, z: 6, kind: 'kids' },
        { x: 36, z: 6, kind: 'sports' },
      ],
    );
    expect(grounds).toHaveLength(2);
    const taken: Parameters<typeof furnish>[2] = { taken: [], benches: false };
    for (const g of grounds) {
      const rivals = grounds.filter((o) => o !== g).map((o) => o.anchor);
      const items = furnish(g, [], { ...taken, rivals });
      expect(items.length).toBeGreaterThan(0);
      for (const item of items) {
        if (g.kind === 'kids') expect(item.x).toBeLessThan(22);
        else expect(item.x).toBeGreaterThan(22);
      }
    }
  });
});

describe('спортивная площадка', () => {
  it('поле: ворота у торцов лицом в поле, остальное - не на поле', () => {
    const rings = [rect(0, 0, 30, 18)];
    const items = furnish(ground(rings, 'sports', { x: 15, z: 9 }), [], { benches: false });
    const goals = items.filter((i) => i.kind === 'goal');
    expect(goals).toHaveLength(2);
    for (const g of goals) {
      const facing = { x: Math.sin(g.angle), z: Math.cos(g.angle) };
      expect(facing.x * (15 - g.x) + facing.z * (9 - g.z)).toBeGreaterThan(0);
    }
    const field = { x: 15, z: 9, angle: 0, hu: 13, hv: 6.5 };
    for (const item of items.filter((i) => i.kind !== 'goal')) {
      expect(rectsOverlap({ ...zone(item), hu: 0.01, hv: 0.01 }, field)).toBe(false);
    }
    expect(items.every((i) => inside(rings, i))).toBe(true);
  });

  it('без поля: турники и теннисный стол', () => {
    const rings = [rect(0, 0, 12, 9)];
    const items = furnish(ground(rings, 'sports', { x: 6, z: 4.5 }), [], { benches: false });
    expect(kinds(items).has('bars')).toBe(true);
    expect(kinds(items).has('table')).toBe(true);
  });
});

describe('модели', () => {
  it('каждый вид собирается в сетки', () => {
    const all = Object.keys(SPECS) as ItemKind[];
    const group = playgroundGroup(all.map((kind, k) => ({ kind, x: k * 8, z: 0, angle: 0 })));
    const names = new Set(group?.children.map((c) => c.name.split('-')[1]));
    for (const kind of all) expect(names.has(kind)).toBe(true);
    for (const child of group?.children ?? []) {
      expect((child as unknown as { geometry: unknown }).geometry).toBeTruthy();
    }
  });
});
