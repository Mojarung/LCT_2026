import { describe, expect, it } from 'vitest';

import { PIT_SIZE_M, pitGroup, pitsOnPaving } from './treePits';
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

const rubber = { rings: [rect(0, 0, 20, 10)], kind: 'special' };
const road = { rings: [rect(30, 0, 50, 10)], kind: 'road' };

describe('лунки деревьев на покрытии', () => {
  it('ствол посреди резины - квадрат 1,6 м по оси площадки на высоте резины', () => {
    const [pit] = pitsOnPaving([{ x: 10, z: 5 }], [rubber], { special: 0.015 });
    expect(pit?.size).toBeCloseTo(PIT_SIZE_M);
    expect(pit?.lift).toBeCloseTo(0.015);
    expect(Math.abs(Math.sin(2 * (pit?.angle ?? 1)))).toBeLessThan(1e-9);
  });

  it('у края резины лунка меньше и не вылезает на газон, вплотную к краю - нет', () => {
    const [near] = pitsOnPaving([{ x: 10, z: 0.9 }], [rubber]);
    expect(near).toBeDefined();
    expect((near?.size ?? 9) / 2).toBeLessThan(0.9);
    expect(pitsOnPaving([{ x: 10, z: 0.3 }], [rubber])).toHaveLength(0);
  });

  it('стороны лунки - вдоль ближайшего края резины, а не по сетке сцены', () => {
    const a = Math.PI / 7;
    const turn = (x: number, z: number) => ({
      x: x * Math.cos(a) + z * Math.sin(a),
      z: -x * Math.sin(a) + z * Math.cos(a),
    });
    const part = { rings: [rect(0, 0, 20, 10).map((p) => turn(p.x, p.z))], kind: 'special' };
    const [pit] = pitsOnPaving([turn(10, 3)], [part]);
    expect(Math.abs(Math.sin(2 * ((pit?.angle ?? 0) - a)))).toBeLessThan(1e-9);
  });

  it('на проезде и вне покрытия лунок нет', () => {
    expect(pitsOnPaving([{ x: 40, z: 5 }], [rubber, road])).toHaveLength(0);
    expect(pitsOnPaving([{ x: 25, z: 5 }], [rubber, road])).toHaveLength(0);
  });

  it('сетки: земля и бортик экземплярами', () => {
    const built = pitGroup(
      pitsOnPaving(
        [
          { x: 5, z: 5 },
          { x: 15, z: 5 },
        ],
        [rubber],
      ),
    );
    const names = built?.group.children.map((c) => c.name) ?? [];
    expect(names).toContain('tree-pit-soil');
    expect(names).toContain('tree-pit-border');
  });
});
