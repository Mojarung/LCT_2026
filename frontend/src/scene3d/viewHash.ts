/* Ракурс 3D-вида в адресе страницы: #view=x,y,z,курс,наклон,режим. Ссылкой на ракурс можно
 * поделиться, а снимок для слайда повторить с той же точки после правки плана. Координаты -
 * метры сцены (от медианы посадок), углы - градусы, чтобы адрес читался человеком. */

import { clampPitch, type Mode, type Pose } from './freecam';

const DEG = 180 / Math.PI;

export function formatView(pose: Pose, mode: Mode): string {
  const n = (v: number, digits: number) => Number(v.toFixed(digits)).toString();
  return `view=${[n(pose.x, 1), n(pose.y, 1), n(pose.z, 1), n(pose.yaw * DEG, 1), n(pose.pitch * DEG, 1), mode].join(',')}`;
}

export function parseView(hash: string): { pose: Pose; mode: Mode } | null {
  const match = /(?:^|[#&])view=([^&]+)/.exec(hash);
  if (!match?.[1]) return null;
  const parts = match[1].split(',');
  const nums = parts.slice(0, 5).map(Number);
  if (nums.length < 5 || nums.some((v) => !Number.isFinite(v))) return null;
  const [x = 0, y = 0, z = 0, yaw = 0, pitch = 0] = nums;
  const mode: Mode = parts[5] === 'walk' ? 'walk' : 'fly';
  return {
    pose: { x, y: Math.max(0.3, y), z, yaw: yaw / DEG, pitch: clampPitch(pitch / DEG) },
    mode,
  };
}
