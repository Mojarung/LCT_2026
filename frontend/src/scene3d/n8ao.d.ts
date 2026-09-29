/** API used from the pinned n8ao 2.0.1 release (the package ships no declarations). */
declare module 'n8ao' {
  import type { Camera, Scene } from 'three';
  import { Pass } from 'three/addons/postprocessing/Pass.js';
  export class N8AOPass extends Pass {
    constructor(scene: Scene, camera: Camera, width?: number, height?: number);
    configuration: {
      aoRadius: number;
      distanceFalloff: number;
      intensity: number;
      gammaCorrection: boolean;
      halfRes: boolean;
      accumulate: boolean;
    };
    setQualityMode(mode: 'Low' | 'Medium' | 'High' | 'Neural-Medium'): void;
  }
}
