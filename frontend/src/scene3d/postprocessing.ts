import * as THREE from 'three';
import { N8AOPass } from 'n8ao';
import { EffectComposer } from 'three/addons/postprocessing/EffectComposer.js';
import { OutputPass } from 'three/addons/postprocessing/OutputPass.js';
import { SMAAPass } from 'three/addons/postprocessing/SMAAPass.js';
import { UnrealBloomPass } from 'three/addons/postprocessing/UnrealBloomPass.js';
import type { Quality } from './engine';

/** Linear HDR → contact occlusion → restrained bloom → display transform → SMAA.
 * The scene's real depth includes alpha-clipped foliage and animated vertices. No
 * replacement normal material: it would turn leaves into solid rectangular cards. */
export class ScenePostprocessing {
  private readonly composer: EffectComposer;
  readonly ao: N8AOPass;
  private readonly bloom: UnrealBloomPass;
  private readonly output = new OutputPass();
  private readonly antialias = new SMAAPass();
  private readonly size = new THREE.Vector2();
  private quality: Quality | null = null;

  constructor(
    private readonly renderer: THREE.WebGLRenderer,
    scene: THREE.Scene,
    camera: THREE.PerspectiveCamera,
  ) {
    const target = new THREE.WebGLRenderTarget(1, 1, {
      type: THREE.HalfFloatType,
      depthBuffer: false,
    });
    this.composer = new EffectComposer(renderer, target);
    // Explicit physical pixels: snapshots and DPR changes must use the same pipeline.
    this.composer.setPixelRatio(1);
    this.ao = new N8AOPass(scene, camera, 1, 1);
    this.ao.configuration.gammaCorrection = false;
    this.ao.configuration.aoRadius = 2;
    this.ao.configuration.distanceFalloff = 1;
    this.ao.configuration.intensity = 1.8;
    // Leaves, people and clouds move even while the camera stands still.
    this.ao.configuration.accumulate = false;
    this.bloom = new UnrealBloomPass(new THREE.Vector2(1, 1), 0.04, 0.25, 5);
    this.composer.addPass(this.ao);
    this.composer.addPass(this.bloom);
    this.composer.addPass(this.output);
    this.composer.addPass(this.antialias);
  }

  apply(quality: Quality): void {
    if (quality === this.quality) return;
    this.quality = quality;
    this.ao.setQualityMode(quality === 'high' ? 'Neural-Medium' : 'Medium');
    this.ao.configuration.halfRes = quality !== 'high';
    this.bloom.enabled = quality === 'high';
  }

  render(): void {
    this.renderer.getDrawingBufferSize(this.size);
    if (
      this.composer.renderTarget1.width !== this.size.x ||
      this.composer.renderTarget1.height !== this.size.y
    ) {
      this.composer.setSize(this.size.x, this.size.y);
    }
    this.composer.render();
  }

  dispose(): void {
    // N8AO 2.0.1 inherits Pass.dispose(), which is empty. Release its own targets,
    // textures and shader materials; never recurse into the borrowed scene/renderer.
    // Its fullscreen triangle geometry is shared across instances, so leave it alone.
    const resources = new Set<THREE.WebGLRenderTarget | THREE.Texture | THREE.Material>();
    for (const value of Object.values(this.ao)) {
      if (
        value instanceof THREE.WebGLRenderTarget ||
        value instanceof THREE.Texture ||
        value instanceof THREE.Material
      )
        resources.add(value);
      else if (
        value &&
        typeof value === 'object' &&
        'material' in value &&
        value.material instanceof THREE.Material
      )
        resources.add(value.material);
    }
    for (const resource of resources) resource.dispose();
    this.bloom.dispose();
    this.output.dispose();
    this.antialias.dispose();
    this.composer.dispose();
  }
}
