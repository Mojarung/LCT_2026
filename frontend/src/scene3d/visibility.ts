/* Видны ли здания в кадре на самом деле, с заслонением.
 *
 * Проекция углов дома в кадр (autoshots.buildingsInView) не знает, что перед домом стоят
 * деревья: дом за кронами считался «в кадре», в промпт фото уходил абзац о фасадах, и модель
 * рисовала дома на месте площадки (Харьковская, 20.10.2026). Здесь кадр рисуется маской в
 * маленький буфер: здания белым, всё остальное чёрным, листва - по своей прозрачности. Доля
 * белых пикселей и есть видимая доля зданий. */

import * as THREE from 'three';

export const MASK_WIDTH = 192;
export const MASK_HEIGHT = 108;
/** Здание в кадре, если видно не меньше этой доли кадра: дальний угол дома между кронами -
 *  ещё не фасад, о котором стоит говорить модели. */
export const VISIBLE_SHARE = 0.02;

type Drawable = THREE.Mesh | THREE.Line | THREE.Points | THREE.Sprite;

function drawable(object: THREE.Object3D): object is Drawable {
  return (
    object instanceof THREE.Mesh ||
    object instanceof THREE.Line ||
    object instanceof THREE.Points ||
    object instanceof THREE.Sprite
  );
}

function cutout(material: THREE.Material | THREE.Material[]): {
  map: THREE.Texture | null;
  alphaTest: number;
} {
  const first = Array.isArray(material) ? material[0] : material;
  const map = (first as THREE.MeshBasicMaterial | undefined)?.map ?? null;
  const alphaTest = first?.alphaTest ?? 0;
  return { map: alphaTest > 0 ? map : null, alphaTest };
}

/** Доля кадра, занятая зданиями, видимыми с камеры (0..1). parts - объекты зданий. */
export function visibleShare(
  renderer: THREE.WebGLRenderer,
  scene: THREE.Scene,
  camera: THREE.Camera,
  parts: ReadonlySet<THREE.Object3D>,
): number {
  const target = new THREE.WebGLRenderTarget(MASK_WIDTH, MASK_HEIGHT);
  const white = new THREE.MeshBasicMaterial({ color: 0xffffff, fog: false });
  const black = new THREE.MeshBasicMaterial({ color: 0x000000, fog: false });
  const cutouts = new Map<string, THREE.MeshBasicMaterial>();
  const saved: { object: Drawable; material: THREE.Material | THREE.Material[] }[] = [];
  const hidden: THREE.Object3D[] = [];
  const background = scene.background;
  const autoUpdate = renderer.shadowMap.autoUpdate;
  const pixels = new Uint8Array(MASK_WIDTH * MASK_HEIGHT * 4);
  try {
    scene.traverse((object) => {
      if (!drawable(object)) return;
      if (!(object instanceof THREE.Mesh)) {
        if (object.visible) {
          hidden.push(object);
          object.visible = false;
        }
        return;
      }
      let building = false;
      for (let o: THREE.Object3D | null = object; o; o = o.parent) {
        if (parts.has(o)) {
          building = true;
          break;
        }
      }
      saved.push({ object, material: object.material });
      if (building) {
        object.material = white;
        return;
      }
      const { map, alphaTest } = cutout(object.material);
      if (!map) {
        object.material = black;
        return;
      }
      const key = `${map.uuid}:${alphaTest}`;
      let leaf = cutouts.get(key);
      if (!leaf) {
        leaf = new THREE.MeshBasicMaterial({
          color: 0x000000,
          map,
          alphaTest,
          side: THREE.DoubleSide,
          fog: false,
        });
        cutouts.set(key, leaf);
      }
      object.material = leaf;
    });
    scene.background = new THREE.Color(0x000000);
    renderer.shadowMap.autoUpdate = false;
    renderer.setRenderTarget(target);
    renderer.clear();
    renderer.render(scene, camera);
    renderer.readRenderTargetPixels(target, 0, 0, MASK_WIDTH, MASK_HEIGHT, pixels);
  } finally {
    renderer.setRenderTarget(null);
    renderer.shadowMap.autoUpdate = autoUpdate;
    scene.background = background;
    for (const { object, material } of saved) object.material = material;
    for (const object of hidden) object.visible = true;
    target.dispose();
    white.dispose();
    black.dispose();
    for (const m of cutouts.values()) m.dispose();
  }
  return countWhite(pixels) / (MASK_WIDTH * MASK_HEIGHT);
}

/** Число белых пикселей RGBA-буфера (красный канал выше половины). */
export function countWhite(pixels: Uint8Array): number {
  let count = 0;
  for (let i = 0; i < pixels.length; i += 4) if ((pixels[i] ?? 0) > 127) count++;
  return count;
}
