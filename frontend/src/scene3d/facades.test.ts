import { describe, expect, it } from 'vitest';

import {
  bayOf,
  facadePlan,
  insideRing,
  mainAxis,
  seriesOf,
  simplifyRing,
  wallsOf,
  yardSide,
} from './facades';
import type { Building, Flat, Line } from './types';

function building(ring: Flat[], extra: Partial<Building> = {}): Building {
  return {
    rings: [ring],
    height: 28.2,
    floors: 9,
    source: 'label',
    kind: 'building',
    wall: 'brick',
    use: 'residential',
    seed: 6,
    ...extra,
  };
}

const rect = (w: number, d: number): Flat[] => [
  { x: 0, z: 0 },
  { x: w, z: 0 },
  { x: w, z: d },
  { x: 0, z: d },
];

describe('серия дома', () => {
  it('каменный жилой дом - серия по этажности, а не по букве «К»', () => {
    expect(seriesOf(building(rect(20, 12), { floors: 17 }))).toBe('tower');
    expect(seriesOf(building(rect(60, 12), { floors: 9 }))).toBe('slab');
    expect(seriesOf(building(rect(60, 12), { floors: 5 }))).toBe('khrushchev');
    expect(seriesOf(building(rect(20, 12), { floors: 3 }))).toBe('brick');
  });

  it('нежилое низкое - павильон, металл - ангар, крыльцо - не дом', () => {
    expect(seriesOf(building(rect(30, 20), { floors: 2, use: 'non_residential' }))).toBe(
      'pavilion',
    );
    expect(seriesOf(building(rect(30, 20), { floors: 1, wall: 'metal' }))).toBe('metal');
    expect(seriesOf(building(rect(3, 2), { kind: 'porch', floors: 1 }))).toBe('porch');
  });
});

describe('контур и ось', () => {
  it('дрожание контура в сантиметры снимается, углы остаются', () => {
    const jitter: Flat[] = [
      { x: 0, z: 0 },
      { x: 10, z: 0.05 },
      { x: 20, z: -0.04 },
      { x: 30, z: 0 },
      { x: 30, z: 12 },
      { x: 15, z: 12.03 },
      { x: 0, z: 12 },
    ];
    const out = simplifyRing(jitter);
    expect(out).toHaveLength(4);
    expect(out).toContainEqual({ x: 30, z: 12 });
  });

  it('ось повёрнутого прямоугольника - вдоль длинной стороны', () => {
    const a = Math.PI / 6;
    const ring = rect(60, 12).map((p) => ({
      x: p.x * Math.cos(a) - p.z * Math.sin(a),
      z: p.x * Math.sin(a) + p.z * Math.cos(a),
    }));
    const axis = mainAxis(ring);
    expect(axis.length).toBeCloseTo(60, 5);
    expect(axis.width).toBeCloseTo(12, 5);
    expect(Math.abs(axis.dx * Math.cos(a) + axis.dz * Math.sin(a))).toBeCloseTo(1, 5);
    expect(insideRing({ x: axis.cx, z: axis.cz }, ring)).toBe(true);
  });

  it('нормали стен смотрят наружу при любом обходе контура', () => {
    for (const ring of [rect(10, 10), [...rect(10, 10)].reverse()]) {
      for (const w of wallsOf(ring, false)) {
        const mx = (w.a.x + w.b.x) / 2 + w.nx;
        const mz = (w.a.z + w.b.z) / 2 + w.nz;
        expect(insideRing({ x: mx, z: mz }, ring)).toBe(false);
      }
    }
  });
});

describe('раскладка фасада', () => {
  const street: Line[] = [
    {
      points: [
        { x: -20, z: -8 },
        { x: 80, z: -8 },
      ],
    },
  ];

  it('подъезды пластины - со двора, по одному на секцию', () => {
    const slab = building(rect(60, 12));
    expect(yardSide(mainAxis(slab.rings[0] ?? []), street, 0)).toBeDefined();
    const plan = facadePlan(slab, street);
    expect(plan.entrances).toHaveLength(2);
    for (const e of plan.entrances) {
      // Двор - сторона z = 12, улица - за бортом на z = -8.
      expect(e.z).toBeCloseTo(12, 5);
      expect(Math.cos(e.angle)).toBeCloseTo(1, 5);
    }
  });

  it('лоджии стопками: тот же пролёт на каждом этаже, не у подъезда и не на первом этаже', () => {
    const slab = building(rect(60, 12));
    const plan = facadePlan(slab, street);
    expect(plan.loggias.length).toBeGreaterThan(0);
    const stacks = new Map<string, number>();
    for (const l of plan.loggias) {
      const key = `${l.x.toFixed(2)}:${l.z.toFixed(2)}`;
      stacks.set(key, (stacks.get(key) ?? 0) + 1);
      expect(l.y).toBeGreaterThan(3);
      for (const e of plan.entrances) {
        const sameWall = Math.abs(l.z - e.z) < 0.01;
        if (sameWall) expect(Math.abs(l.x - e.x)).toBeGreaterThanOrEqual(bayOf('slab') * 1.5);
      }
    }
    for (const floors of stacks.values()) expect(floors).toBe(8);
  });

  it('пятиэтажка - открытые балконы, башня - машинное помещение на крыше', () => {
    const five = facadePlan(building(rect(60, 12), { floors: 5, height: 16.2 }), street);
    expect(five.loggias.every((l) => !l.glazed)).toBe(true);
    expect(five.roofBoxes).toHaveLength(0);
    const tower = facadePlan(building(rect(24, 18), { floors: 17, height: 52.2 }), street);
    expect(tower.roofBoxes).toHaveLength(1);
    expect(tower.roofBoxes[0]?.y).toBeCloseTo(52.2);
    expect(tower.entrances).toHaveLength(1);
  });

  it('одноэтажный павильон модулей не получает', () => {
    const plan = facadePlan(
      building(rect(30, 20), { floors: 1, height: 4, use: 'non_residential' }),
      street,
    );
    expect(plan.loggias).toHaveLength(0);
    expect(plan.entrances).toHaveLength(0);
  });
});
