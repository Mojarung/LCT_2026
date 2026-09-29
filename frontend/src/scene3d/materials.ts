import * as THREE from 'three';
import grassColor from './assets/grass_diff.jpg';
import grassNormal from './assets/grass_nor_gl.jpg';
import grassArm from './assets/grass_arm.jpg';
import asphaltColor from './assets/asphalt_diff.jpg';
import asphaltNormal from './assets/asphalt_nor_gl.jpg';
import asphaltArm from './assets/asphalt_arm.jpg';
import paversColor from './assets/pavers_diff.jpg';
import paversNormal from './assets/pavers_nor_gl.jpg';
import paversArm from './assets/pavers_arm.jpg';

/** 1K scanned materials, bundled locally: nine RGBA mip chains ≈48 MiB on GPU.
 * ARM packs ambient occlusion, roughness and metalness. Sources are in assets/sources.json. */
export async function loadGroundMaterials(anisotropy: number) {
  const loader = new THREE.TextureLoader();
  const urls = [
    grassColor,
    asphaltColor,
    paversColor,
    grassNormal,
    asphaltNormal,
    paversNormal,
    grassArm,
    asphaltArm,
    paversArm,
  ];
  const results = await Promise.allSettled(
    urls.map((url, index) =>
      loader.loadAsync(url).then((texture) => {
        texture.wrapS = texture.wrapT = THREE.RepeatWrapping;
        texture.anisotropy = anisotropy;
        texture.colorSpace = index < 3 ? THREE.SRGBColorSpace : THREE.NoColorSpace;
        return texture;
      }),
    ),
  );
  const failed = results.find((r) => r.status === 'rejected');
  if (failed) {
    for (const r of results) if (r.status === 'fulfilled') r.value.dispose();
    throw new Error('Не удалось загрузить материалы 3D. Обновите страницу.');
  }
  const textures = results.map((r) => (r as PromiseFulfilledResult<THREE.Texture>).value);
  const [
    grass,
    asphalt,
    pavers,
    grassNormalMap,
    asphaltNormalMap,
    paversNormalMap,
    grassArmMap,
    asphaltArmMap,
    paversArmMap,
  ] = textures as [
    THREE.Texture,
    THREE.Texture,
    THREE.Texture,
    THREE.Texture,
    THREE.Texture,
    THREE.Texture,
    THREE.Texture,
    THREE.Texture,
    THREE.Texture,
  ];
  return {
    grass,
    asphalt,
    pavers,
    grassNormalMap,
    asphaltNormalMap,
    paversNormalMap,
    grassArmMap,
    asphaltArmMap,
    paversArmMap,
    textures,
  };
}
