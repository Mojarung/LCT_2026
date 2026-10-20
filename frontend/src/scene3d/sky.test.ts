import * as THREE from 'three';
import { describe, expect, it, vi } from 'vitest';

import { moonState, sceneTime } from './celestial';
import { Atmosphere, sunColor, turned } from './sky';
import { clearance, clusters, pointAt, route, spine, tourPose, tourRoute } from './tour';
import type { Flat } from './types';

describe('луна', () => {
  it('в полнолуние 25.01.2024 диск освещён почти весь, в новолуние 11.01.2024 - почти нет', () => {
    expect(moonState(Date.UTC(2024, 0, 25, 17, 54)).fraction).toBeGreaterThan(0.98);
    expect(moonState(Date.UTC(2024, 0, 11, 11, 57)).fraction).toBeLessThan(0.02);
  });

  it('за неделю после новолуния луна растёт, за неделю до - убывает', () => {
    expect(moonState(Date.UTC(2024, 0, 18)).waxing).toBe(true);
    expect(moonState(Date.UTC(2024, 0, 4)).waxing).toBe(false);
  });

  it('высота и азимут в своих пределах, момент сцены - московское время', () => {
    const m = moonState(sceneTime(182, 23));
    expect(Math.abs(m.elevation)).toBeLessThanOrEqual(90);
    expect(m.azimuth).toBeGreaterThanOrEqual(0);
    expect(m.azimuth).toBeLessThan(360);
    expect(sceneTime(1, 3)).toBe(Date.UTC(2026, 0, 1, 0));
  });
});

/** Улица буквой Г: 200 м на восток и 150 м на север, плюс двор в стороне от угла. */
function lStreet(): Flat[] {
  const points: Flat[] = [];
  for (let x = 0; x <= 200; x += 4) points.push({ x, z: 0 }, { x, z: 6 });
  for (let z = 0; z >= -150; z -= 4) points.push({ x: 200, z }, { x: 206, z });
  for (let x = 80; x <= 100; x += 4) points.push({ x, z: 40 });
  return points;
}

describe('облёт', () => {
  it('хребет идёт от конца до конца улицы и не заходит во двор сбоку', () => {
    const line = spine(clusters(lStreet()));
    const ends = [line[0], line[line.length - 1]].map((p) => ({
      x: Math.round(p?.x ?? 0),
      z: Math.round(p?.z ?? 0),
    }));
    const west = ends.find((p) => p.x < 30);
    const north = ends.find((p) => p.z < -120);
    expect(west).toBeDefined();
    expect(north).toBeDefined();
    expect(line.every((p) => p.z < 30)).toBe(true);
  });

  it('маршрут размечен по длине, точка на середине лежит на середине', () => {
    const r = route([
      { x: 0, z: 0 },
      { x: 100, z: 0 },
    ]);
    expect(r.length).toBeCloseTo(100);
    expect(pointAt(r, 50).x).toBeCloseTo(50);
    expect(pointAt(r, 500).x).toBeCloseTo(100);
  });

  it('камера смотрит вперёд по ходу, а на обратном пути - назад по маршруту', () => {
    const r = route([
      { x: 0, z: 0 },
      { x: 300, z: 0 },
    ]);
    // Вперёд - на восток: курс -90 градусов (0 - север, против часовой - налево).
    expect(tourPose(r, 50).yaw).toBeCloseTo(-Math.PI / 2);
    const back = tourPose(r, 300 + 100);
    expect(back.x).toBeCloseTo(200);
    expect(back.yaw).toBeCloseTo(Math.PI / 2);
    expect(back.pitch).toBeLessThan(0);
  });

  it('облетать нечего - маршрута нет', () => {
    expect(tourRoute([])).toBeNull();
    expect(tourRoute([{ x: 0, z: 0 }])).toBeNull();
    expect(tourRoute(lStreet())?.length).toBeGreaterThan(250);
  });
});

describe('высота облёта', () => {
  it('над домом в 17 этажей камера идёт выше крыши, вдали от него - на базовой высоте', () => {
    const r = route([
      { x: 0, z: 0 },
      { x: 600, z: 0 },
    ]);
    const tower = { minX: 290, minZ: 5, maxX: 310, maxZ: 25, height: 52.2 };
    const heights = clearance(r, [tower]);
    const at = (x: number) => heights[Math.round(x / 5)] ?? 0;
    expect(at(300)).toBeGreaterThanOrEqual(52.2 + 10 - 0.01);
    expect(at(10)).toBeCloseTo(30);
    expect(at(590)).toBeCloseTo(30);
    // Подъём начинается до дома, а не у стены.
    expect(at(260)).toBeGreaterThan(40);
    expect(tourPose(r, 300, heights).y).toBeGreaterThan(62);
  });
});

describe('поворот солнца', () => {
  it('крутит азимут по кругу и не трогает высоту', () => {
    const sun = { azimuth: 350, elevation: 30 };
    expect(turned(sun, 20)).toEqual({ azimuth: 10, elevation: 30 });
    expect(turned(sun, -360)).toEqual({ azimuth: 350, elevation: 30 });
    expect(turned(sun, 0)).toBe(sun);
  });
});

describe('цвет солнца', () => {
  it('у горизонта тёплый, в полдень почти белый', () => {
    const low = sunColor(0);
    const high = sunColor(60);
    expect(low.r).toBeCloseTo(1, 5);
    expect(low.b).toBeCloseTo(0.36, 5);
    expect(high.b).toBeCloseTo(0.92, 5);
    expect(sunColor(20).b).toBeGreaterThan(low.b);
    expect(sunColor(20).b).toBeLessThan(high.b);
  });
});

describe('атмосфера сцены', () => {
  /** Рендерер без WebGL: карта окружения подменяется пустой целью, экспозиция - число. */
  function atmosphere() {
    vi.spyOn(THREE.PMREMGenerator.prototype, 'fromScene').mockImplementation(
      () => new THREE.WebGLRenderTarget(1, 1),
    );
    vi.spyOn(THREE.PMREMGenerator.prototype, 'dispose').mockImplementation(() => undefined);
    const renderer = { toneMappingExposure: 1 } as unknown as THREE.WebGLRenderer;
    const scene = new THREE.Scene();
    return { atmosphere: new Atmosphere(renderer, scene), renderer, scene };
  }

  it('кладёт в сцену небо, солнце с тенью, рассеянный свет и дымку', () => {
    const { atmosphere: a, scene } = atmosphere();
    expect(scene.children).toContain(a.sky);
    expect(scene.children).toContain(a.sun);
    expect(scene.children).toContain(a.hemi);
    expect(scene.fog).toBe(a.fog);
    expect(a.sun.castShadow).toBe(true);
    expect(a.sky.scale.x).toBe(4500);
    expect(a.sky.material.uniforms.turbidity?.value).toBe(4.5);
  });

  it('летний полдень: солнце высоко, светло, ночи нет, карта окружения в сцене', () => {
    const { atmosphere: a, renderer, scene } = atmosphere();
    a.apply({ season: 'summer', hour: 13, clouds: 0, shadowSize: 2048, shadowExtent: 80 });
    expect(a.state.elevation).toBeGreaterThan(40);
    expect(a.state.night).toBe(0);
    expect(a.state.direction.y).toBeGreaterThan(0.6);
    expect(a.sun.intensity).toBeGreaterThan(4);
    expect(a.sun.shadow.mapSize.x).toBe(2048);
    expect(a.sun.shadow.camera.left).toBe(-80);
    expect(a.hemi.color.getHex()).toBe(0xc8dcff);
    expect(renderer.toneMappingExposure).toBeCloseTo(0.64, 2);
    expect(scene.environment).not.toBeNull();
    expect(a.sky.material.uniforms.showSunDisc?.value).toBe(1);
  });

  it('зимняя полночь: светит луна или небо, свет голубой и слабый, дымка тёмная', () => {
    const { atmosphere: a, renderer } = atmosphere();
    a.apply({ season: 'winter', hour: 0 });
    expect(a.state.elevation).toBeLessThan(-20);
    expect(a.state.night).toBe(1);
    expect(a.state.color.getHex()).toBe(0x9fb2d6);
    expect(a.state.intensity).toBeLessThan(0.4);
    expect(a.hemi.color.getHex()).toBe(0x6f7fa8);
    expect(a.fog.color.b).toBeLessThan(0.2);
    expect(renderer.toneMappingExposure).toBeCloseTo(0.42, 5);
  });

  it('облака гасят солнце и сгущают дымку, осадки добавляют плотность', () => {
    const { atmosphere: a } = atmosphere();
    a.apply({ hour: 13, clouds: 0, fog: 0 });
    const clear = { sun: a.sun.intensity, fog: a.fog.density };
    a.apply({ clouds: 1, fog: 0.002 });
    expect(a.sun.intensity).toBeLessThan(clear.sun);
    expect(a.fog.density).toBeCloseTo(clear.fog + 0.0005 + 0.002, 6);
    expect(a.sun.shadow.radius).toBeCloseTo(4, 5);
  });

  it('поворот на 180 градусов разворачивает солнце, высота та же', () => {
    const { atmosphere: a } = atmosphere();
    a.apply({ hour: 10, turn: 0 });
    const before = a.state.direction.clone();
    a.apply({ turn: 180 });
    expect(a.state.direction.y).toBeCloseTo(before.y, 5);
    expect(a.state.direction.x).toBeCloseTo(-before.x, 5);
    expect(a.state.direction.z).toBeCloseTo(-before.z, 5);
  });

  it('тень идёт за фокусом шагами в пиксель, небо - за камерой', () => {
    const { atmosphere: a } = atmosphere();
    a.apply({ hour: 12, shadowSize: 100, shadowExtent: 50 });
    a.follow(new THREE.Vector3(10.3, 0, -4.2), 5);
    const target = a.sun.target.position;
    const offset = a.sun.position.clone().sub(target);
    expect(offset.length()).toBeCloseTo(600, 3);
    expect(offset.normalize().dot(a.state.direction)).toBeCloseTo(1, 5);
    expect(target.distanceTo(new THREE.Vector3(10.3, 0, -4.2))).toBeLessThan(1);
    expect(a.sky.material.uniforms.time?.value).toBe(5);
    const camera = new THREE.PerspectiveCamera();
    camera.position.set(100, 20, -30);
    a.center(camera);
    expect(a.sky.position.toArray()).toEqual([100, 20, -30]);
    a.dispose();
  });
});
