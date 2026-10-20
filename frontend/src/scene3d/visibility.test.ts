import * as THREE from 'three';
import { describe, expect, it } from 'vitest';
import { countWhite, MASK_HEIGHT, MASK_WIDTH, VISIBLE_SHARE, visibleShare } from './visibility';

describe('building mask', () => {
  it('counts only bright pixels of the RGBA mask', () => {
    const pixels = new Uint8Array([
      255, 255, 255, 255, 0, 0, 0, 255, 200, 200, 200, 255, 90, 0, 0, 255,
    ]);
    expect(countWhite(pixels)).toBe(2);
  });
});

describe('видимая доля зданий', () => {
  /** Рендерер без WebGL: «рисует» маску - белый, если материал здания белый. */
  function fakeRenderer(scene: THREE.Scene, seen: Map<THREE.Object3D, THREE.Material>) {
    const calls: string[] = [];
    let white = 0;
    const renderer = {
      shadowMap: { autoUpdate: true },
      setRenderTarget: (t: unknown) => calls.push(t ? 'target' : 'screen'),
      clear: () => calls.push('clear'),
      render: () => {
        calls.push('render');
        scene.traverse((o) => {
          if (o instanceof THREE.Mesh) {
            const m = o.material as THREE.MeshBasicMaterial;
            seen.set(o, m);
            if (m.color.getHex() === 0xffffff) white += 1;
          }
        });
        expect(renderer.shadowMap.autoUpdate).toBe(false);
        expect((scene.background as THREE.Color).getHex()).toBe(0);
      },
      readRenderTargetPixels: (
        _t: unknown,
        _x: number,
        _y: number,
        w: number,
        h: number,
        out: Uint8Array,
      ) => {
        // Белыми - столько строк маски, сколько зданий нарисовано белым.
        for (let i = 0; i < w * white * 4; i++) out[i] = 255;
        expect(h).toBe(MASK_HEIGHT);
      },
    };
    return {
      renderer: renderer as unknown as THREE.WebGLRenderer,
      calls,
      auto: renderer.shadowMap,
    };
  }

  it('здания белым, прочее чёрным, листва - по своей прозрачности, потом всё как было', () => {
    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0x87ceeb);
    const house = new THREE.Group();
    const wall = new THREE.Mesh(new THREE.BoxGeometry(), new THREE.MeshStandardMaterial());
    house.add(wall);
    const roadMaterial = new THREE.MeshStandardMaterial();
    const road = new THREE.Mesh(new THREE.PlaneGeometry(), roadMaterial);
    const leafMap = new THREE.Texture();
    const leafMaterial = new THREE.MeshStandardMaterial({ map: leafMap, alphaTest: 0.5 });
    const leaves = new THREE.Mesh(new THREE.PlaneGeometry(), [leafMaterial]);
    const line = new THREE.Line(new THREE.BufferGeometry());
    const wallMaterial = wall.material;
    scene.add(house, road, leaves, line);
    const seen = new Map<THREE.Object3D, THREE.Material>();
    const { renderer, calls, auto } = fakeRenderer(scene, seen);
    const share = visibleShare(renderer, scene, new THREE.PerspectiveCamera(), new Set([house]));
    expect(share).toBeCloseTo(1 / MASK_HEIGHT, 6);
    expect(calls).toEqual(['target', 'clear', 'render', 'screen']);
    expect((seen.get(wall) as THREE.MeshBasicMaterial).color.getHex()).toBe(0xffffff);
    expect((seen.get(road) as THREE.MeshBasicMaterial).color.getHex()).toBe(0);
    const leaf = seen.get(leaves) as THREE.MeshBasicMaterial;
    expect(leaf.map).toBe(leafMap);
    expect(leaf.alphaTest).toBe(0.5);
    // После маски сцена прежняя.
    expect(wall.material).toBe(wallMaterial);
    expect(road.material).toBe(roadMaterial);
    expect(leaves.material).toEqual([leafMaterial]);
    expect(line.visible).toBe(true);
    expect(auto.autoUpdate).toBe(true);
    expect(scene.background.getHex()).toBe(0x87ceeb);
  });

  it('без зданий доля ноль; доля видимости в кадре - от двух процентов', () => {
    const scene = new THREE.Scene();
    scene.add(new THREE.Mesh(new THREE.BoxGeometry(), new THREE.MeshStandardMaterial()));
    const { renderer } = fakeRenderer(scene, new Map());
    expect(visibleShare(renderer, scene, new THREE.PerspectiveCamera(), new Set())).toBe(0);
    expect(VISIBLE_SHARE).toBe(0.02);
    expect(MASK_WIDTH * MASK_HEIGHT).toBe(192 * 108);
  });
});
