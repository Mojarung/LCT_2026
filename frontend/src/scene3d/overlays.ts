/* Рабочие слои 3D-вида: подземные сети и граница работ поверх земли.
 *
 * 3D смотрят и при работе с планом: видно, почему дерево не встало у кабеля или почему газон
 * пустой у теплотрассы. Сети рисуются лентами на земле цветами 2D-карты (map/palette.ts,
 * токены --c-*), граница работ - тёмной лентой. Свет на ленты не действует, чтобы цвет сети
 * читался в тени и ночью. В кадры для фото слои не попадают (engine.ts). */

import * as THREE from 'three';

import { ribbonBox } from './ground';
import type { Line } from './types';

/** Цвета сетей - как на плане (светлая тема tokens.css). */
export const UTILITY_COLORS: Record<string, string> = {
  'utility.water': '#2f74b5',
  'utility.sewer': '#7d5a3a',
  'utility.storm': '#2f8f8f',
  'utility.drain': '#2f8f8f',
  'utility.heat': '#b0661c',
  'utility.gas': '#9a861a',
  'utility.power_cable': '#c0392b',
  'utility.telecom': '#6f469a',
  'utility.access': '#7a7264',
  power_line_overhead: '#c0392b',
};
const OTHER = '#7a7264';
const BOUNDARY = '#2b2620';
/** Ленты на 4 см над землёй: выше травы и шва бортового камня. */
const LIFT_M = 0.04;

/** Лента на земле (видна вблизи) и линия в пиксель поверх неё (видна с любой высоты). */
function band(lines: readonly Line[], width: number, color: string): THREE.Group {
  const group = new THREE.Group();
  const mesh = new THREE.Mesh(
    ribbonBox(lines, width, 0.015, LIFT_M),
    new THREE.MeshBasicMaterial({
      color,
      polygonOffset: true,
      polygonOffsetFactor: -2,
      polygonOffsetUnits: -2,
    }),
  );
  mesh.renderOrder = 2;
  const points: number[] = [];
  for (const line of lines) {
    for (let i = 0; i + 1 < line.points.length; i++) {
      const a = line.points[i];
      const b = line.points[i + 1];
      if (a && b) points.push(a.x, LIFT_M + 0.03, a.z, b.x, LIFT_M + 0.03, b.z);
    }
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.Float32BufferAttribute(points, 3));
  const thin = new THREE.LineSegments(geometry, new THREE.LineBasicMaterial({ color }));
  thin.renderOrder = 3;
  group.add(mesh, thin);
  return group;
}

export function utilityOverlay(utilities: readonly { kind: string; lines: Line[] }[]): THREE.Group {
  const group = new THREE.Group();
  group.name = 'overlay-utilities';
  for (const { kind, lines } of utilities) {
    if (lines.length) group.add(band(lines, 0.6, UTILITY_COLORS[kind] ?? OTHER));
  }
  return group;
}

export function boundaryOverlay(lines: readonly Line[]): THREE.Group {
  const group = new THREE.Group();
  group.name = 'overlay-boundary';
  if (lines.length) group.add(band(lines, 0.9, BOUNDARY));
  return group;
}
