import * as THREE from 'three';
import { describe, expect, it, vi } from 'vitest';

import { fakeContext, type FakeContext } from '../test/canvas';
import {
  buildMask,
  fenceBarSpots,
  fenceFrame,
  groundMesh,
  type GroundTextures,
  type MaskInfo,
  paintContextRoads,
  ROAD_DROP_M,
  streetLightGeometry,
  type SurfaceImage,
  withoutHairpins,
} from './ground';
import { ASPHALT, GRASS, PAVERS, PAVERS_RGB, ROAD_RGB, SOIL_RGB } from './surfaceMask';
import type { Flat, World } from './types';

/* Маска земли по холсту: jsdom не рисует, поэтому холст подменяется маленьким растеризатором.
 * Заливка контура (moveTo, lineTo, fill) красит пиксели, центр которых внутри контура
 * (чёт-нечет), getImageData и putImageData работают с буфером холста. Прочее (сдвиг, масштаб,
 * drawImage, размытие) только записывается (fakeContext). */

const SIZE_M = 40;
const MPP = 0.25;
const PX = SIZE_M / MPP;

interface PixelCanvas {
  fake: FakeContext;
  fills: string[];
}

function parseColor(s: string): [number, number, number] {
  const hex = /^#([0-9a-f]{6})$/i.exec(s);
  if (hex) {
    const n = parseInt(hex[1] ?? '0', 16);
    return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
  }
  const rgb = /rgb\((\d+),\s*(\d+),\s*(\d+)\)/.exec(s);
  return rgb ? [Number(rgb[1]), Number(rgb[2]), Number(rgb[3])] : [0, 0, 0];
}

function insidePath(
  paths: readonly (readonly [number, number])[][],
  x: number,
  y: number,
): boolean {
  let inside = false;
  for (const ring of paths) {
    for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
      const [xi, yi] = ring[i] ?? [0, 0];
      const [xj, yj] = ring[j] ?? [0, 0];
      if (yi > y !== yj > y && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside;
    }
  }
  return inside;
}

function pixelContext(width: number, height: number): PixelCanvas {
  const fake = fakeContext({ width, height });
  const buffer = new Uint8ClampedArray(width * height * 4);
  const fills: string[] = [];
  let paths: [number, number][][] = [];
  Object.assign(fake.ctx, {
    beginPath: () => {
      paths = [];
    },
    moveTo: (x: number, y: number) => {
      paths.push([[x, y]]);
    },
    lineTo: (x: number, y: number) => {
      paths[paths.length - 1]?.push([x, y]);
    },
    closePath: () => undefined,
    clearRect: () => {
      buffer.fill(0);
    },
    fill: () => {
      const style = typeof fake.ctx.fillStyle === 'string' ? fake.ctx.fillStyle : '';
      fills.push(style);
      const [r, g, b] = parseColor(style);
      for (let row = 0; row < height; row++) {
        for (let col = 0; col < width; col++) {
          if (insidePath(paths, col + 0.5, row + 0.5))
            buffer.set([r, g, b, 255], (row * width + col) * 4);
        }
      }
    },
    getImageData: (_x: number, _y: number, w: number, h: number) => ({
      width: w,
      height: h,
      data: buffer.slice(0, w * h * 4),
    }),
    putImageData: (img: ImageData) => {
      buffer.set(img.data);
    },
  });
  return { fake, fills };
}

/** Холсты, созданные кодом: у каждого свой растеризатор, первый - холст маски. */
function installPixels(): PixelCanvas[] {
  const made: PixelCanvas[] = [];
  const own = new WeakMap<HTMLCanvasElement, PixelCanvas>();
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockImplementation(function (
    this: HTMLCanvasElement,
  ) {
    let pc = own.get(this);
    if (!pc) {
      pc = pixelContext(this.width, this.height);
      own.set(this, pc);
      made.push(pc);
    }
    return pc.fake.ctx as unknown as RenderingContext;
  } as HTMLCanvasElement['getContext']);
  return made;
}

function world(over: Partial<World> = {}): World {
  return {
    origin: [1000, 2000],
    bounds: [0, 0, SIZE_M, SIZE_M],
    buildings: [],
    plants: [],
    curbs: [],
    fences: [],
    poles: [],
    lawns: [],
    sidewalks: [],
    roads: [],
    floorsBy: { label: 0, neighbor: 0, letter: 0, assumed: 0 },
    fallback: false,
    ...over,
  };
}

/** Прямоугольник сцены x0..x1, z0..z1 кольцом в координатах чертежа (начало 1000, 2000). */
const rect = (x0: number, z0: number, x1: number, z1: number): number[][][] => [
  [
    [1000 + x0, 2000 - z0],
    [1000 + x1, 2000 - z0],
    [1000 + x1, 2000 - z1],
    [1000 + x0, 2000 - z1],
    [1000 + x0, 2000 - z0],
  ],
];

/** Грунт на всю сцену, проезд посередине (x 10..30, z 15..25) и плитка у края. */
function surface(road = rect(10, 15, 30, 25)): SurfaceImage {
  return {
    img: {} as HTMLImageElement,
    origin: [1000, 1960],
    cell: 0.5,
    width: 80,
    height: 80,
    areas: {
      soil: [rect(0, 0, SIZE_M, SIZE_M)],
      paved: [road, rect(32.5, 5, 37.5, 15)],
      paved_kind: ['road', 'pavers'],
    },
  };
}

const at = (mask: MaskInfo, x: number, z: number) =>
  Math.floor(z / mask.metresPerPx) * mask.width + Math.floor(x / mask.metresPerPx);

describe('маска земли по контурам карты покрытий', () => {
  it('растр по 0,25 м на всю сцену, проезд, газон и плитка - по видам контуров', () => {
    const canvases = installPixels();
    const mask = buildMask(world(), surface());
    expect([mask.width, mask.height, mask.metresPerPx]).toEqual([PX, PX, MPP]);
    expect(mask.rect).toEqual([0, 0, SIZE_M, SIZE_M]);
    expect(mask.road[at(mask, 20, 20)]).toBe(1);
    expect(mask.road[at(mask, 5, 35)]).toBe(0);
    expect(mask.kinds[at(mask, 20, 20)]).toBe(ASPHALT);
    expect(mask.kinds[at(mask, 5, 35)]).toBe(GRASS);
    expect(mask.kinds[at(mask, 35, 10)]).toBe(PAVERS);
    // Всё снято картой покрытий: город вокруг сюда не ляжет.
    expect(mask.known.every((v) => v === 1)).toBe(true);
    // Сначала грунт, поверх - покрытия своими цветами.
    expect(canvases[0]?.fills.slice(0, 3)).toEqual([
      `rgb(${SOIL_RGB.join(', ')})`,
      `rgb(${ROAD_RGB.join(', ')})`,
      `rgb(${PAVERS_RGB.join(', ')})`,
    ]);
  });

  it('текстура маски: газон, плитка и проезд по каналам, непрозрачная, без мип-уровней', () => {
    installPixels();
    const mask = buildMask(world(), surface());
    const data = mask.texture.image.data as Uint8Array;
    const px = (x: number, z: number) => {
      const i = at(mask, x, z) * 4;
      return Array.from(data.subarray(i, i + 4));
    };
    expect(px(20, 20)).toEqual([0, 0, 255, 255]);
    expect(px(5, 35)).toEqual([255, 0, 0, 255]);
    expect(px(35, 10)).toEqual([0, 255, 0, 255]);
    expect(mask.texture.generateMipmaps).toBe(false);
    expect(mask.texture.flipY).toBe(false);
    expect(mask.cut.unpackAlignment).toBe(1);
    expect((mask.cut.image.data as Uint8Array)[at(mask, 20, 20)]).toBe(255);
    expect(mask.grass).toBeInstanceOf(THREE.DataTexture);
  });

  it('бортовой камень по краю проезда, поребрик - у плитки с газоном', () => {
    installPixels();
    const mask = buildMask(world(), surface());
    const roadPoints = mask.edges.road.flatMap((l) => l.points);
    expect(roadPoints.length).toBeGreaterThan(3);
    for (const p of roadPoints) {
      expect(p.x).toBeGreaterThan(9);
      expect(p.x).toBeLessThan(31);
      expect(p.z).toBeGreaterThan(14);
      expect(p.z).toBeLessThan(26);
    }
    const garden = mask.edges.garden.flatMap((l) => l.points);
    expect(garden.length).toBeGreaterThan(3);
    for (const p of garden) expect(p.x).toBeGreaterThan(31);
    expect(mask.roadContours?.length).toBeGreaterThan(0);
  });

  it('маленькое пятно проезда не опускается: проезд - от 60 кв. м', () => {
    installPixels();
    const mask = buildMask(world(), surface(rect(10, 10, 12.5, 12.5)));
    expect(mask.road.every((v) => v === 0)).toBe(true);
    expect(mask.edges.road).toHaveLength(0);
  });
});

describe('маска земли без контуров', () => {
  it('без карты покрытий - газон, полигоны подосновы поверх: проезд, тротуар, газон', () => {
    const canvases = installPixels();
    const square = (x0: number, x1: number) => [
      { x: x0, z: x0 },
      { x: x1, z: x0 },
      { x: x1, z: x1 },
      { x: x0, z: x1 },
    ];
    const mask = buildMask(
      world({ roads: [[square(2, 20)]], sidewalks: [[square(30, 36)]], lawns: [[square(22, 26)]] }),
      null,
    );
    expect(mask.known.every((v) => v === 0)).toBe(true);
    expect(mask.grass).toBeUndefined();
    expect(canvases[0]?.fills).toEqual(['#0000ff', '#00ff00', '#ff0000']);
    expect(mask.road[at(mask, 15, 15)]).toBe(1);
    expect(mask.kinds[at(mask, 24, 24)]).toBe(GRASS);
    expect(mask.kinds[at(mask, 33, 33)]).toBe(PAVERS);
    expect(mask.kinds[at(mask, 38, 2)]).toBe(GRASS);
    expect(mask.edges.road.length).toBeGreaterThan(0);
  });

  it('растр старого прогона кладётся с отражением по вертикали и размывается на клетку', () => {
    const canvases = installPixels();
    const img = { naturalWidth: 80, naturalHeight: 80 } as HTMLImageElement;
    const raster: SurfaceImage = { img, origin: [1000, 1960], cell: 0.5, width: 80, height: 80 };
    buildMask(world(), raster);
    const fake = canvases[0]?.fake;
    // Левый край растра - x сцены 0, нижний - z сцены 40 (Y чертежа 1960).
    expect(fake?.named('translate')[0]?.args).toEqual([0, 160]);
    expect(fake?.named('scale')[0]?.args).toEqual([2, -2]);
    expect(fake?.named('drawImage')[0]?.args[0]).toBe(img);
    // Клетка 0,5 м = 2 пикселя маски: размытие на 1,8 пикселя.
    expect(fake?.named('drawImage')[1]?.state).toBeDefined();
    expect(canvases.length).toBeGreaterThan(1);
  });
});

function plainMask(): MaskInfo {
  const n = 16 * 16;
  const data = new Uint8Array(n * 4);
  for (let i = 0; i < n; i++) data.set([255, 0, 0, 255], i * 4);
  return {
    texture: new THREE.DataTexture(data, 16, 16),
    rect: [-2, -3, 16, 16],
    kinds: new Uint8Array(n),
    known: new Uint8Array(n),
    edges: { road: [], garden: [] },
    road: new Uint8Array(n),
    cut: new THREE.DataTexture(new Uint8Array(n), 16, 16),
    width: 16,
    height: 16,
    metresPerPx: 1,
  };
}

const TEX: GroundTextures = {
  grass: new THREE.Texture(),
  asphalt: new THREE.Texture(),
  pavers: new THREE.Texture(),
  noise: new THREE.Texture(),
};
const WEATHER = { uWet: { value: 0.3 }, uSnow: { value: 0 } };

function compiled(mesh: THREE.Mesh) {
  const material = mesh.material as THREE.MeshStandardMaterial;
  const shader = {
    uniforms: {} as Record<string, THREE.IUniform>,
    vertexShader: '#include <common>\n#include <worldpos_vertex>',
    fragmentShader:
      '#include <common>\n#include <map_fragment>\n#include <roughnessmap_fragment>\n#include <normal_fragment_maps>',
  };
  material.onBeforeCompile(
    shader as unknown as THREE.WebGLProgramParametersWithUniforms,
    {} as THREE.WebGLRenderer,
  );
  return { shader, material };
}

describe('лист земли', () => {
  it('земля - квадрат на сцену и поле вокруг, в центре сцены', () => {
    const mesh = groundMesh(world(), plainMask(), TEX, WEATHER);
    expect(mesh.name).toBe('ground');
    expect(mesh.receiveShadow).toBe(true);
    mesh.geometry.computeBoundingBox();
    const box = mesh.geometry.boundingBox ?? new THREE.Box3();
    expect(box.max.x - box.min.x).toBeCloseTo(SIZE_M + 6000, 3);
    expect((box.max.x + box.min.x) / 2).toBeCloseTo(20, 3);
    expect(box.max.y).toBeCloseTo(0, 6);
  });

  it('проезд - по прямоугольнику маски на высоту борта ниже', () => {
    const mesh = groundMesh(world(), plainMask(), TEX, WEATHER, { road: true });
    expect(mesh.name).toBe('road-surface');
    mesh.geometry.computeBoundingBox();
    const box = mesh.geometry.boundingBox ?? new THREE.Box3();
    expect([box.min.x, box.min.z, box.max.x, box.max.z]).toEqual([-2, -3, 14, 13]);
    expect(box.min.y).toBeCloseTo(-ROAD_DROP_M, 6);
    const { shader } = compiled(mesh);
    expect(shader.uniforms.uRoad?.value).toBe(1);
  });

  it('шейдер получает маску, фактуры, погоду и код земли; PBR - только при парах карт', () => {
    const geometry = new THREE.PlaneGeometry(1, 1);
    const tex: GroundTextures = {
      ...TEX,
      grassNormalMap: new THREE.Texture(),
      grassArmMap: new THREE.Texture(),
      asphaltNormalMap: new THREE.Texture(),
    };
    const mask = plainMask();
    const mesh = groundMesh(world(), mask, tex, WEATHER, {
      geometry,
      cutRoad: true,
      name: 'paving',
      cover: 'pavers',
    });
    expect(mesh.geometry).toBe(geometry);
    expect(mesh.name).toBe('paving');
    const { shader, material } = compiled(mesh);
    const u = shader.uniforms;
    expect(u.uMask?.value).toBe(mask.texture);
    expect((u.uMaskRect?.value as THREE.Vector4).toArray()).toEqual([-2, -3, 16, 16]);
    expect((u.uPbr?.value as THREE.Vector3).toArray()).toEqual([1, 0, 0]);
    expect(u.uAsphaltArm?.value).toBe(TEX.noise);
    expect(u.uCover?.value).toBe(1);
    expect(u.uCutRoad?.value).toBe(1);
    expect(u.uWet).toBe(WEATHER.uWet);
    expect(u.uLitter?.value).toBe(0);
    expect(shader.vertexShader).toContain('vGroundPos = (modelMatrix');
    expect(shader.fragmentShader).toContain('uniform sampler2D uMask;');
    expect(shader.fragmentShader).not.toContain('#include <map_fragment>');
    expect(material.customProgramCacheKey()).toBe('green-ground');
    const asphalt = compiled(groundMesh(world(), mask, TEX, WEATHER, { cover: 'asphalt' }));
    expect(asphalt.shader.uniforms.uCover?.value).toBe(2);
    expect(asphalt.shader.uniforms.uCutRoad?.value).toBe(0);
  });
});

describe('дороги карты города на маске', () => {
  function stroked(region: (col: number, row: number) => boolean) {
    const fake = fakeContext({ width: 16, height: 16 });
    const data = new Uint8ClampedArray(16 * 16 * 4);
    for (let row = 0; row < 16; row++)
      for (let col = 0; col < 16; col++)
        if (region(col, row)) data.set([255, 255, 255, 255], (row * 16 + col) * 4);
    Object.assign(fake.ctx, { getImageData: () => ({ width: 16, height: 16, data }) });
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockImplementation(() => fake.ctx);
    return fake;
  }
  const line = {
    points: [
      { x: 0, z: 5 },
      { x: 12, z: 5 },
    ],
  };

  it('дорожка ложится плиткой на газон дальнего поля, лента - шириной дороги', () => {
    const fake = stroked((_c, row) => row >= 6 && row <= 10);
    const mask = plainMask();
    paintContextRoads(mask, [{ width: 3, paved: 'pavers', lines: [line] }]);
    const data = mask.texture.image.data as Uint8Array;
    const i = 8 * 16 + 8;
    expect(data[i * 4]).toBe(0);
    expect(data[i * 4 + 1]).toBe(255);
    expect(mask.kinds[i]).toBe(PAVERS);
    expect(mask.kinds[0]).toBe(GRASS);
    expect(mask.texture.version).toBeGreaterThan(0);
    expect(fake.named('stroke')[0]?.state.lineWidth).toBe(3);
    expect(fake.named('moveTo')[0]?.args).toEqual([2, 8]);
  });

  it('проезд карты - асфальт; снятое съёмкой и опущенный проезд не трогаются', () => {
    stroked((_c, row) => row >= 6 && row <= 10);
    const mask = plainMask();
    const surveyed = 8 * 16 + 8;
    mask.road[8 * 16 + 2] = 1;
    mask.known.fill(0);
    mask.known[surveyed] = 1;
    paintContextRoads(mask, [{ width: 3, paved: 'asphalt', lines: [line] }]);
    // Снятый пиксель закрывает поле вокруг на 30 м: вся маска 16 м - рядом со съёмкой.
    expect(mask.kinds.every((k) => k === GRASS)).toBe(true);
    expect(mask.texture.version).toBe(0);
    const far = plainMask();
    stroked((_c, row) => row >= 6 && row <= 10);
    far.road[8 * 16 + 2] = 1;
    paintContextRoads(far, [{ width: 3, paved: 'asphalt', lines: [line] }]);
    expect(far.kinds[8 * 16 + 8]).toBe(ASPHALT);
    expect(far.kinds[8 * 16 + 2]).toBe(GRASS);
    expect((far.texture.image.data as Uint8Array)[(8 * 16 + 8) * 4 + 1]).toBe(0);
  });
});

describe('ограды и опоры', () => {
  const fence = {
    points: [
      { x: 0, z: 0 },
      { x: 3, z: 0 },
      { x: 3, z: 4 },
    ],
  };

  it('прутья решётки с шагом вдоль всей ломаной, перенос остатка через угол', () => {
    const spots = fenceBarSpots([fence], 1);
    expect(spots).toHaveLength(7);
    expect(spots[0]).toEqual({ x: 0.5, z: 0 });
    expect(spots[2]).toEqual({ x: 2.5, z: 0 });
    expect(spots[3]?.x).toBe(3);
    expect(spots[3]?.z).toBeCloseTo(0.5, 6);
    expect(fenceBarSpots([], 1)).toEqual([]);
  });

  it('каркас: столбы на концах и через 2,5 м, не ближе 1,2 м друг к другу, и два перила', () => {
    const g = fenceFrame([fence]);
    const pos = g.getAttribute('position');
    expect(g.getAttribute('normal').count).toBe(pos.count);
    let top = 0;
    const posts = new Set<string>();
    for (let i = 0; i < pos.count; i++) {
      top = Math.max(top, pos.getY(i));
      if (pos.getY(i) > 1.05) posts.add(`${pos.getX(i).toFixed(2)},${pos.getZ(i).toFixed(2)}`);
    }
    expect(top).toBeCloseTo(1.1, 5);
    // Столб - четыре верхних угла: концы (0,0), (3,4) и промежуточные (2,5;0), (3;2) - (3,0)
    // ближе 1,2 м к (2,5;0) не встаёт.
    expect(posts.size / 4).toBe(4);
  });

  it('опора освещения: ствол уходит под землю, светильник на консоли в +z, бетон светлее стали', () => {
    const g = streetLightGeometry();
    g.computeBoundingBox();
    const box = g.boundingBox ?? new THREE.Box3();
    expect(box.min.y).toBeCloseTo(-0.2, 5);
    expect(box.max.y).toBeGreaterThan(8.8);
    expect(box.max.z).toBeCloseTo(1.98, 2);
    const color = g.getAttribute('color');
    expect(color.count).toBe(g.getAttribute('position').count);
    expect(color.getX(0)).toBeCloseTo(0.2, 5);
    expect(color.getX(color.count - 1)).toBeCloseTo(0.07, 5);
  });
});

describe('контур без шпилек', () => {
  it('вершина, где контур разворачивается назад, снимается; кольцо остаётся замкнутым', () => {
    const ring = [
      { x: 0, z: 0 },
      { x: 10, z: 0 },
      { x: 10, z: 10 },
      { x: 5, z: 10 },
      { x: 9, z: 10.2 },
      { x: 0, z: 10 },
      { x: 0, z: 0 },
    ];
    const out = withoutHairpins(ring);
    expect(out[0]).toEqual(out[out.length - 1]);
    expect(out).not.toContainEqual({ x: 9, z: 10.2 });
    expect(out.length).toBeLessThan(ring.length);
  });

  it('точки ближе 5 см к соседу снимаются, кольцо замкнуто; пустое - пустое', () => {
    expect(withoutHairpins([])).toEqual([]);
    const square = [
      { x: 0, z: 0 },
      { x: 0, z: 0.01 },
      { x: 4, z: 0 },
      { x: 4, z: 4 },
      { x: 0, z: 4 },
      { x: 0, z: 0 },
    ];
    const out = withoutHairpins(square);
    expect(out[0]).toEqual(out[out.length - 1]);
    for (let i = 0; i + 1 < out.length; i++) {
      const a = out[i] as Flat;
      const b = out[i + 1] as Flat;
      expect(Math.hypot(b.x - a.x, b.z - a.z)).toBeGreaterThan(0.05);
    }
  });
});
