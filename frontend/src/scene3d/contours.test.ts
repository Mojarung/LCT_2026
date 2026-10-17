import { describe, expect, it } from 'vitest';

import {
  chaikin,
  chain,
  contours,
  dominantAngles,
  isoSegments,
  outlines,
  roundCorners,
  simplify,
  snapToAngles,
} from './contours';

function disc(w: number, h: number, cx: number, cy: number, r: number): Uint8Array {
  const v = new Uint8Array(w * h);
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) v[y * w + x] = Math.hypot(x - cx, y - cy) <= r ? 255 : 0;
  }
  return v;
}

describe('контуры маски', () => {
  it('круг даёт одну замкнутую линию на радиусе', () => {
    const grid = { values: disc(80, 80, 40, 40, 20), width: 80, height: 80 };
    const lines = chain(isoSegments(grid, 128, 1));
    expect(lines).toHaveLength(1);
    const line = lines[0] ?? [];
    for (const [x, y] of line) expect(Math.abs(Math.hypot(x - 40, y - 40) - 20)).toBeLessThan(1);
    const first = line[0];
    const last = line[line.length - 1];
    expect(first && last && Math.hypot(first[0] - last[0], first[1] - last[1])).toBeLessThan(1e-6);
  });

  it('полоса проезда - две линии по краям, в метрах сцены', () => {
    const w = 100;
    const h = 60;
    const values = new Uint8Array(w * h);
    for (let y = 20; y < 40; y++) for (let x = 0; x < w; x++) values[y * w + x] = 255;
    const lines = contours({ values, width: w, height: h }, [100, 200, 25, 15], 0.25);
    expect(lines).toHaveLength(2);
    const zs = lines.map((l) => l.points.reduce((s, p) => s + p.z, 0) / l.points.length).sort();
    expect(zs[0]).toBeCloseTo(200 + 20 * 0.25, 0);
    expect(zs[1]).toBeCloseTo(200 + 40 * 0.25, 0);
  });

  it('упрощение снимает лишние точки прямой, сглаживание оставляет концы', () => {
    const straight: [number, number][] = [
      [0, 0],
      [1, 0.001],
      [2, 0],
      [3, 0],
    ];
    expect(simplify(straight, 0.01)).toHaveLength(2);
    const corner: [number, number][] = [
      [0, 0],
      [10, 0],
      [10, 10],
    ];
    const smooth = chaikin(corner);
    expect(smooth[0]).toEqual([0, 0]);
    expect(smooth[smooth.length - 1]).toEqual([10, 10]);
    expect(smooth.length).toBeGreaterThan(corner.length);
  });
});

describe('ровные контуры', () => {
  it('волнистый край прямоугольника становится прямым, контур замкнут', () => {
    const w = 120;
    const h = 80;
    const values = new Uint8Array(w * h);
    for (let y = 0; y < h; y++) {
      for (let x = 0; x < w; x++) {
        // Верхний край гуляет на пиксель-два, как клетки карты покрытий.
        const top = 20 + ((x * 7) % 3);
        if (y >= top && y < 60 && x >= 10 && x < 110) values[y * w + x] = 255;
      }
    }
    const lines = outlines({ values, width: w, height: h }, [0, 0, 30, 20], 0.25);
    expect(lines).toHaveLength(1);
    const pts = lines[0]?.points ?? [];
    expect(pts[0]).toEqual(pts[pts.length - 1]);
    // Точки верхней стороны (вдали от углов) лежат на одной прямой.
    const top = pts.filter((p) => p.z < 10 && p.x > 6 && p.x < 24).map((p) => p.z);
    expect(top.length).toBeGreaterThan(0);
    // Волна растра - 0,5 м; после выпрямления сторона отходит от прямой меньше чем на 8 см.
    expect(Math.max(...top) - Math.min(...top)).toBeLessThan(0.08);
  });

  it('скругление не трогает середину длинной стороны и срезает угол не больше cap', () => {
    const square: [number, number][] = [
      [0, 0],
      [40, 0],
      [40, 40],
      [0, 40],
      [0, 0],
    ];
    const r = roundCorners(square, 2, 1);
    for (const [x, y] of r) {
      const corner = Math.min(
        Math.hypot(x, y),
        Math.hypot(x - 40, y),
        Math.hypot(x - 40, y - 40),
        Math.hypot(x, y - 40),
      );
      expect(corner).toBeGreaterThanOrEqual(2 - 1e-9);
    }
  });
});

describe('тонкие контуры', () => {
  it('щель шириной в полметра посреди проезда не даёт своего контура', () => {
    const w = 200;
    const h = 120;
    const values = new Uint8Array(w * h);
    // Проезд 40 x 20 м при 0,25 м на пиксель, в нём щель 0,5 x 15 м.
    for (let y = 20; y < 100; y++) for (let x = 20; x < 180; x++) values[y * w + x] = 255;
    for (let y = 50; y < 52; y++) for (let x = 60; x < 120; x++) values[y * w + x] = 0;
    const grid = { values, width: w, height: h };
    expect(outlines(grid, [0, 0, 50, 30], 0.25)).toHaveLength(2);
    expect(outlines(grid, [0, 0, 50, 30], 0.25, { minWidth: 1.5 })).toHaveLength(1);
  });
});

describe('главные направления участка', () => {
  it('стены под 30° дают направление 30°, кривой край газона встаёт параллельно', () => {
    const a = (30 * Math.PI) / 180;
    const wall = (len: number, ox: number) => ({
      points: [
        { x: ox, z: 0 },
        { x: ox + Math.cos(a) * len, z: Math.sin(a) * len },
      ],
    });
    const angles = dominantAngles([wall(40, 0), wall(25, 50)]);
    expect(angles[0]).toBeCloseTo(a, 1);
    // Контур, стороны которого отклонены от 30° и 120° на 3-6°: концы сдвигаются до 0,6 м.
    const tilt = (deg: number, len: number): [number, number] => [
      Math.cos((deg * Math.PI) / 180) * len,
      Math.sin((deg * Math.PI) / 180) * len,
    ];
    const loop: [number, number][] = [[0, 0]];
    for (const [deg, len] of [
      [33, 20],
      [126, 10],
      [207, 20],
      [294, 10],
    ] as const) {
      const last = loop[loop.length - 1] ?? [0, 0];
      const [dx, dy] = tilt(deg, len);
      loop.push([last[0] + dx, last[1] + dy]);
    }
    loop[loop.length - 1] = [0, 0];
    const snapped = snapToAngles(loop, angles);
    for (let i = 0; i + 1 < snapped.length; i++) {
      const [ax, ay] = snapped[i] ?? [0, 0];
      const [bx, by] = snapped[i + 1] ?? [0, 0];
      const deg = ((((Math.atan2(by - ay, bx - ax) * 180) / Math.PI) % 90) + 90) % 90;
      expect(Math.min(Math.abs(deg - 30), 90 - Math.abs(deg - 30))).toBeLessThan(0.5);
    }
  });
});

describe('выравнивание не перекраивает участок', () => {
  it('длинная сторона, отклонённая на 10°, остаётся как есть', () => {
    const loop: [number, number][] = [
      [0, 0],
      [Math.cos(0.17) * 30, Math.sin(0.17) * 30],
      [Math.cos(0.17) * 30 - 5, Math.sin(0.17) * 30 + 5],
      [-5, 5],
      [0, 0],
    ];
    const snapped = snapToAngles(loop, [0]);
    expect(snapped[1]?.[1]).toBeCloseTo(loop[1]?.[1] ?? 0, 1);
  });
});
