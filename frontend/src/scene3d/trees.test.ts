import * as THREE from 'three';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { Archetype } from './archetypes';
import {
  barkMaterial,
  coreMaterial,
  crownCore,
  farGeometry,
  Forest,
  generateModel,
  leafMaterial,
  type WindUniforms,
} from './trees';
import type { Plant, SceneSpeciesJson } from './types';

/* Модели ez-tree в jsdom строятся за десятки миллисекунд (куст 'lo' ~60 мс, дерево 'hi' ~90 мс),
 * поэтому тесты генерируют настоящие модели, но малым числом архетипов. */

const linden: SceneSpeciesJson = {
  name_ru: 'Липа мелколистная',
  name_lat: 'Tilia cordata',
  life_form: 'tree_large',
  height_m: 25,
  crown_diameter_m: 6,
  crown_mature_m: 12,
  evergreen: false,
  conifer: false,
  growth: 'medium',
  genus: 'tilia',
  family: 'Malvaceae',
};

const lilac: SceneSpeciesJson = {
  ...linden,
  name_ru: 'Сирень',
  life_form: 'shrub_medium',
  height_m: 3,
  crown_diameter_m: 1.5,
  crown_mature_m: 2.5,
  genus: 'syringa',
};

/** Существующий куст с чётным seed: архетип 'shrub', вариант 0 - одна модель на всех. */
function oldShrub(id: string, x: number, z: number, seed = 2): Plant {
  return {
    id,
    x,
    z,
    type: 'existing_shrub',
    code: '',
    name: 'куст',
    species: lilac,
    existing: true,
    existingRadius: 1,
    seed,
  };
}

function newTree(id: string, x: number, z: number, seed = 3600): Plant {
  return {
    id,
    x,
    z,
    type: 'tree',
    code: 'tilia_cordata',
    name: 'Липа',
    species: linden,
    existing: false,
    seed,
  };
}

function wind(): WindUniforms {
  return {
    uTime: { value: 0 },
    uWind: { value: 0.35 },
    uSunView: { value: new THREE.Vector3(0, 1, 0) },
    uSunColor: { value: new THREE.Color(1, 1, 1) },
    uSnow: { value: 0 },
  };
}

/** Шейдер с теми include, которые подменяют материалы деревьев. */
function fakeShader(): THREE.WebGLProgramParametersWithUniforms {
  return {
    uniforms: {},
    vertexShader: '#include <common>\n#include <project_vertex>\n',
    fragmentShader:
      '#include <common>\n#include <clipping_planes_fragment>\n#include <normal_fragment_begin>\n' +
      '#include <normal_fragment_maps>\n#include <emissivemap_fragment>\n',
  } as unknown as THREE.WebGLProgramParametersWithUniforms;
}

function compile(material: THREE.Material): THREE.WebGLProgramParametersWithUniforms {
  const shader = fakeShader();
  material.onBeforeCompile(shader, {} as THREE.WebGLRenderer);
  return shader;
}

function box(min: [number, number, number], max: [number, number, number]): THREE.Box3 {
  return new THREE.Box3(new THREE.Vector3(...min), new THREE.Vector3(...max));
}

function bounds(geometry: THREE.BufferGeometry): THREE.Box3 {
  geometry.computeBoundingBox();
  return geometry.boundingBox as THREE.Box3;
}

describe('ядро кроны', () => {
  const leaves = box([-2, 1, -2], [2, 5, 2]);

  it('у лиственного - бугристая сфера внутри облака листвы', () => {
    const core = crownCore(leaves, 'broadleaf', 1);
    const b = bounds(core);
    expect(core.getAttribute('position').count).toBe(
      new THREE.IcosahedronGeometry(1, 4).getAttribute('position').count,
    );
    // Заполнение 0,24 размера с буграми до 1,26: ядро не выходит за листву.
    expect(leaves.containsBox(b)).toBe(true);
    expect(b.max.x - b.min.x).toBeLessThan(4 * 0.24 * 2 * 1.3);
    expect(b.getCenter(new THREE.Vector3()).y).toBeCloseTo(3, 0);
    expect(core.getAttribute('normal')).toBeDefined();
  });

  it('у хвойного - конус, у стелющегося можжевельника - сфера', () => {
    const cone = new THREE.ConeGeometry(1, 1, 10, 6).getAttribute('position').count;
    expect(crownCore(leaves, 'spruce', 1).getAttribute('position').count).toBe(cone);
    expect(crownCore(leaves, 'creeper', 1).getAttribute('position').count).not.toBe(cone);
  });

  it('у ажурной берёзы ядро уже, чем у куста', () => {
    const width = (a: Archetype) => {
      const b = bounds(crownCore(leaves, a, 0));
      return b.max.x - b.min.x;
    };
    expect(width('birch')).toBeLessThan(width('broadleaf'));
    expect(width('broadleaf')).toBeLessThan(width('shrub'));
  });

  it('бугры зависят от seed: варианты одной формы различаются', () => {
    const a = crownCore(leaves, 'oak', 1).getAttribute('position').array;
    const b = crownCore(leaves, 'oak', 4.7).getAttribute('position').array;
    expect(Array.from(a)).not.toEqual(Array.from(b));
  });
});

describe('дальняя модель', () => {
  const leaves = box([-3, 2, -3], [3, 8, 3]);

  it('крона с цветом экземпляра (aAccent = 1), ствол без него, всего меньше пары сотен граней', () => {
    const far = farGeometry(leaves, 'broadleaf');
    const accent = Array.from(far.getAttribute('aAccent').array);
    const crown = accent.filter((v) => v === 1).length;
    const trunk = accent.filter((v) => v === 0).length;
    expect(crown).toBe(
      new THREE.IcosahedronGeometry(1, 1).toNonIndexed().getAttribute('position').count,
    );
    expect(trunk).toBe(
      new THREE.CylinderGeometry(0.5, 0.6, 1, 5, 1).toNonIndexed().getAttribute('position').count,
    );
    expect(far.getAttribute('position').count / 3).toBeLessThan(200);
    expect(far.getAttribute('color').count).toBe(accent.length);
    expect(far.boundingSphere).not.toBeNull();
  });

  it('ствол стоит от земли под кроной, тёмный', () => {
    const far = farGeometry(leaves, 'broadleaf');
    const pos = far.getAttribute('position');
    const acc = far.getAttribute('aAccent');
    const col = far.getAttribute('color');
    let minY = Infinity;
    let maxY = -Infinity;
    for (let i = 0; i < pos.count; i++) {
      if (acc.getX(i) !== 0) continue;
      minY = Math.min(minY, pos.getY(i));
      maxY = Math.max(maxY, pos.getY(i));
      expect(col.getX(i)).toBeLessThan(0.1);
    }
    expect(minY).toBeCloseTo(0, 5);
    // Высота ствола - до четверти кроны над её низом: 2 + 6 * 0,25.
    expect(maxY).toBeCloseTo(3.5, 5);
  });

  it('у хвойного конус почти во всю высоту кроны, без бугров', () => {
    const far = farGeometry(leaves, 'pine');
    const pos = far.getAttribute('position');
    const acc = far.getAttribute('aAccent');
    let top = -Infinity;
    let bottom = Infinity;
    let crown = 0;
    for (let i = 0; i < pos.count; i++) {
      if (acc.getX(i) !== 1) continue;
      crown++;
      top = Math.max(top, pos.getY(i));
      bottom = Math.min(bottom, pos.getY(i));
    }
    expect(crown).toBe(
      new THREE.ConeGeometry(1, 1, 7, 1).toNonIndexed().getAttribute('position').count,
    );
    expect(top - bottom).toBeCloseTo(6 * 0.95, 5);
  });
});

describe('материалы деревьев', () => {
  it('кора качается ветром и белеет снегом сверху, ключ программы свой', () => {
    const w = wind();
    const m = barkMaterial({ map: null, normalMap: null, aoMap: null }, w);
    const shader = compile(m);
    expect(shader.uniforms.uWind).toBe(w.uWind);
    expect(shader.uniforms.uSnow).toBe(w.uSnow);
    expect(shader.vertexShader).toContain('windWorld.xz += sway');
    expect(shader.vertexShader).not.toContain('#define GREEN_LEAF');
    expect(shader.vertexShader).not.toContain('#include <project_vertex>');
    expect(shader.fragmentShader).toContain('uniform float uSnow;');
    expect(shader.fragmentShader).toContain('snowUp');
    expect(m.customProgramCacheKey()).toBe('green-bark');
    expect(m.roughness).toBeCloseTo(0.92);
  });

  it('листва трепещет, просвечивает против солнца, отсекает прозрачное', () => {
    const w = wind();
    const map = new THREE.Texture();
    const m = leafMaterial(map, w);
    const shader = compile(m);
    expect(m.map).toBe(map);
    expect(m.vertexColors).toBe(true);
    expect(m.alphaTest).toBeCloseTo(0.35);
    expect(m.side).toBe(THREE.DoubleSide);
    expect(shader.uniforms.uSunView).toBe(w.uSunView);
    expect(shader.uniforms.uSunColor).toBe(w.uSunColor);
    expect(shader.vertexShader).toContain('#define GREEN_LEAF');
    expect(shader.fragmentShader).toContain('backLit');
    expect(shader.fragmentShader).toContain('normal = normalize(vNormal);');
    expect(m.customProgramCacheKey()).toBe('green-leaf');
  });

  it('ядро кроны проявляется издали и пятнами отбрасывает пиксели', () => {
    const w = wind();
    const m = coreMaterial(w);
    const shader = compile(m);
    expect(shader.uniforms.uTime).toBe(w.uTime);
    expect(shader.vertexShader).toContain('vCoreWorld = windWorld.xyz;');
    expect(shader.fragmentShader).toContain('float coreNoise(vec3 p)');
    expect(shader.fragmentShader).toContain('smoothstep(18.0, 45.0');
    expect(shader.fragmentShader).toContain('discard;');
    expect(m.customProgramCacheKey()).toBe('green-crown-core');
  });
});

describe('модель ez-tree', () => {
  it('лёгкая детализация втрое беднее листвой, размеры кроны те же по порядку', () => {
    const hi = generateModel('shrub', 0, 'hi');
    const lo = generateModel('shrub', 0, 'lo');
    const hiLeaves = hi.leaves.getAttribute('position').count;
    const loLeaves = lo.leaves.getAttribute('position').count;
    expect(loLeaves).toBeLessThan(hiLeaves * 0.5);
    expect(lo.size.widthX / hi.size.widthX).toBeGreaterThan(0.6);
    expect(lo.size.widthX / hi.size.widthX).toBeLessThan(1.6);
  });

  it('листья получают оттенок по высоте и нормали от центра кроны', () => {
    const model = generateModel('shrub', 1, 'lo');
    const color = model.leaves.getAttribute('color');
    expect(color.normalized).toBe(true);
    for (let i = 0; i < color.count; i += 37) {
      expect(color.getX(i)).toBeGreaterThanOrEqual(0.72 - 1e-6);
      expect(color.getX(i)).toBeLessThanOrEqual(1);
      expect(color.getX(i)).toBe(color.getY(i));
    }
    const normal = model.leaves.getAttribute('normal');
    for (let i = 0; i < normal.count; i += 41) {
      expect(Math.hypot(normal.getX(i), normal.getY(i), normal.getZ(i))).toBeCloseTo(1, 4);
    }
  });

  it('ядро и дальняя модель сидят в мерке кроны, а не в рамке выбросов', () => {
    const model = generateModel('shrub', 0, 'lo');
    const core = bounds(model.core);
    const halfX = model.size.widthX / 2;
    expect(core.min.x).toBeGreaterThanOrEqual(model.size.centerX - halfX);
    expect(core.max.x).toBeLessThanOrEqual(model.size.centerX + halfX);
    const far = bounds(model.far);
    expect(far.max.x - far.min.x).toBeLessThanOrEqual(model.size.widthX * 1.2);
    expect(model.far.getAttribute('aAccent')).toBeDefined();
  });

  it('поправки архетипа: кора берёзы, листья ясеня у широколиственного', () => {
    expect(generateModel('birch', 0, 'lo').bark).toBe('birch');
    expect(generateModel('broadleaf', 0, 'lo').leafType).toBe('ash');
  });

  it('третий вариант широколиственного - другое ветвление, а не клон', () => {
    const a = generateModel('broadleaf', 0, 'lo');
    const c = generateModel('broadleaf', 2, 'lo');
    expect(c.leaves.getAttribute('position').count).not.toBe(
      a.leaves.getAttribute('position').count,
    );
  });
});

/* Лес. Камера в (0, 2, 0) смотрит на -Z: дистанция до посадки - почти её |z|. */

function camera(): THREE.PerspectiveCamera {
  const cam = new THREE.PerspectiveCamera(60, 1.5, 0.1, 5000);
  cam.position.set(0, 2, 0);
  cam.lookAt(0, 2, -1);
  cam.updateMatrixWorld();
  return cam;
}

interface Meshes {
  branches: THREE.InstancedMesh;
  leaves: THREE.InstancedMesh;
  core: THREE.InstancedMesh;
}

/** Группы моделей в порядке, в котором их собирает Forest: hi, lo (по три сетки) и силуэт. */
function groupsOf(forest: Forest): { hi: Meshes; lo: Meshes; far: THREE.InstancedMesh }[] {
  const meshes = forest.root.children.filter(
    (c): c is THREE.InstancedMesh => c instanceof THREE.InstancedMesh,
  );
  const out = [];
  for (let i = 0; i + 6 < meshes.length; i += 7) {
    const at = (k: number) => meshes[i + k] as THREE.InstancedMesh;
    out.push({
      hi: { branches: at(0), leaves: at(1), core: at(2) },
      lo: { branches: at(3), leaves: at(4), core: at(5) },
      far: at(6),
    });
  }
  return out;
}

function extrasOf(forest: Forest): { mulch: THREE.InstancedMesh; stakes: THREE.InstancedMesh } {
  const root = forest.root.children[0] as THREE.Group;
  return {
    mulch: root.children[0] as THREE.InstancedMesh,
    stakes: root.children[1] as THREE.InstancedMesh,
  };
}

describe('лес экземплярами', () => {
  beforeEach(() => {
    vi.stubGlobal('requestAnimationFrame', (cb: FrameRequestCallback) => {
      cb(0);
      return 0;
    });
  });

  it('одна модель на архетип и вариант: шесть кустов - одно задание', () => {
    const forest = new Forest([
      oldShrub('a', 0, -5, 2),
      oldShrub('b', 0, -6, 4),
      oldShrub('c', 0, -7, 6),
      oldShrub('d', 0, -8, 1),
    ]);
    // seed 1 - нечётный: 'shrub_dense', вариант 1.
    expect(forest.jobs).toEqual(
      expect.arrayContaining([
        { archetype: 'shrub', variant: 0 },
        { archetype: 'shrub_dense', variant: 1 },
      ]),
    );
    expect(forest.jobs).toHaveLength(2);
  });

  it('детализация по расстоянию: вблизи полная, дальше лёгкая, вдали силуэт, за пределом нет', async () => {
    const plants = [
      oldShrub('near', 0, -10),
      oldShrub('mid', 0, -50),
      oldShrub('far', 0, -200),
      oldShrub('gone', 0, -1500),
      oldShrub('behind', 0, 300),
    ];
    const forest = new Forest(plants);
    const steps: [number, number][] = [];
    await forest.build((done, total) => steps.push([done, total]));
    expect(steps).toEqual([[1, 1]]);
    forest.update(camera(), 1.5);
    expect(forest.wind.uTime.value).toBe(1.5);
    const [group] = groupsOf(forest);
    if (!group) throw new Error('нет группы');
    // Кусту лёгкая модель с половины lodDistance (30 м), силуэт - с 90 м, предел 900 м.
    expect(group.hi.branches.count).toBe(1);
    expect(group.hi.leaves.count).toBe(1);
    expect(group.hi.core.count).toBe(1);
    expect(group.lo.branches.count).toBe(1);
    expect(group.far.count).toBe(1);
    // Матрица экземпляра на ветвях, листьях и ядре - один буфер.
    expect(group.hi.leaves.instanceMatrix).toBe(group.hi.branches.instanceMatrix);
    const m = new THREE.Matrix4();
    group.hi.branches.getMatrixAt(0, m);
    const p = new THREE.Vector3().setFromMatrixPosition(m);
    expect(p.z).toBeCloseTo(-10);
    group.far.getMatrixAt(0, m);
    expect(new THREE.Vector3().setFromMatrixPosition(m).z).toBeCloseTo(-200);
    forest.dispose();
  });

  it('зимой у лиственного куста остаются только ветви', async () => {
    const forest = new Forest([oldShrub('a', 0, -10)]);
    await forest.build(() => undefined);
    forest.apply({ season: 'winter' });
    forest.update(camera(), 0);
    const [group] = groupsOf(forest);
    expect(group?.hi.branches.count).toBe(1);
    expect(group?.hi.leaves.count).toBe(0);
    expect(group?.hi.core.count).toBe(0);
  });

  it('без существующих насаждений их нет ни в кадре, ни в прицеле', async () => {
    const forest = new Forest([oldShrub('a', 0, -10), oldShrub('b', 3, -12)]);
    await forest.build(() => undefined);
    expect(forest.bodies()).toHaveLength(2);
    // Кэш прицела: тот же массив, пока ничего не менялось.
    expect(forest.bodies()).toBe(forest.bodies());
    const body = forest.bodies()[0];
    expect(body?.x).toBe(0);
    expect(body?.z).toBe(-10);
    expect(body?.radius).toBeGreaterThan(0);
    forest.apply({ showExisting: false });
    expect(forest.bodies()).toHaveLength(0);
    forest.update(camera(), 0);
    expect(groupsOf(forest)[0]?.hi.branches.count).toBe(0);
  });

  it('кадр без движения камеры не перекладывает экземпляры', async () => {
    const forest = new Forest([oldShrub('a', 0, -10)]);
    await forest.build(() => undefined);
    const cam = camera();
    forest.update(cam, 0);
    const group = groupsOf(forest)[0];
    if (!group) throw new Error('нет группы');
    group.hi.branches.count = 99;
    forest.update(cam, 1);
    expect(group.hi.branches.count).toBe(99);
    cam.position.set(0, 2, 0.5);
    cam.updateMatrixWorld();
    forest.update(cam, 2);
    expect(group.hi.branches.count).toBe(1);
  });

  it('размер существующего - по радиусу кроны с подосновы, нового - по возрасту', () => {
    const forest = new Forest([]);
    const old = forest.sizeOf({ ...oldShrub('a', 0, 0), existingRadius: 1.5 });
    expect(old.crown).toBeCloseTo(3);
    const young = forest.sizeOf(newTree('t', 0, 0));
    forest.apply({ age: 30 });
    const grown = forest.sizeOf(newTree('t', 0, 0));
    expect(grown.height).toBeGreaterThan(young.height);
    expect(grown.crown).toBeGreaterThan(young.crown);
  });

  it('у молодого дерева мульча и три кола, с возрастом колья снимают, потом и круг', async () => {
    const forest = new Forest([newTree('t1', 0, -10), newTree('t2', 5, -10), oldShrub('s', 0, -4)]);
    await forest.build(() => undefined);
    const { mulch, stakes } = extrasOf(forest);
    // По умолчанию 10 лет: круг есть, кольев нет; существующий куст не в счёт.
    expect(mulch.count).toBe(2);
    expect(stakes.count).toBe(0);
    forest.apply({ age: 2 });
    expect(mulch.count).toBe(2);
    expect(stakes.count).toBe(6);
    const m = new THREE.Matrix4();
    stakes.getMatrixAt(0, m);
    const at = new THREE.Vector3().setFromMatrixPosition(m);
    expect(Math.hypot(at.x, at.z + 10)).toBeCloseTo(0.45, 5);
    mulch.getMatrixAt(0, m);
    const scale = new THREE.Vector3().setFromMatrixScale(m);
    expect(scale.x).toBeGreaterThanOrEqual(0.7);
    expect(scale.x).toBeLessThanOrEqual(1.2);
    forest.apply({ age: 40 });
    expect(mulch.count).toBe(0);
    expect(stakes.count).toBe(0);
    forest.dispose();
  });

  it('экземпляр масштабирован в размер плана и повёрнут по seed', async () => {
    const tree = newTree('t', 4, -20, 900);
    const forest = new Forest([tree]);
    await forest.build(() => undefined);
    forest.update(camera(), 0);
    const group = groupsOf(forest)[0];
    if (!group) throw new Error('нет группы');
    expect(group.hi.branches.count).toBe(1);
    const m = new THREE.Matrix4();
    group.hi.branches.getMatrixAt(0, m);
    const pos = new THREE.Vector3();
    const q = new THREE.Quaternion();
    const scale = new THREE.Vector3();
    m.decompose(pos, q, scale);
    expect(pos.x).toBeCloseTo(4);
    expect(pos.z).toBeCloseTo(-20);
    // seed 900 из 3600 - четверть оборота вокруг вертикали.
    const angle = 2 * Math.acos(Math.min(1, Math.abs(q.w)));
    expect(angle).toBeCloseTo(Math.PI / 2, 4);
    const body = forest.bodies()[0];
    const size = forest.sizeOf(tree);
    expect(body?.height).toBeGreaterThan(size.height * 0.9);
    expect(body?.height).toBeLessThan(size.height * 1.1);
    // Цвет листвы экземпляра - летний зелёный.
    const color = new THREE.Color();
    group.hi.leaves.getColorAt(0, color);
    expect(color.g).toBeGreaterThan(color.r);
    expect(color.g).toBeGreaterThan(color.b);
  });
});
