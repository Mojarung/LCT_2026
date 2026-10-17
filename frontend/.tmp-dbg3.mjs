import { chromium } from '@playwright/test';
const b = await chromium.launch({ channel: 'chrome', args: ['--use-angle=d3d11', '--enable-gpu', '--ignore-gpu-blocklist'] });
const p = await b.newPage({ viewport: { width: 1600, height: 900 } });
await p.goto('http://localhost:5173/runs/01a0dccf-b370-7389-8cbf-b35ec61f502c/3d#view=20,12,40,-60,-35,fly');
await p.waitForFunction(() => window.__scene, null, { timeout: 240000 });
await p.waitForTimeout(6000);
const info = await p.evaluate(() => {
  const e = window.__scene;
  const m = e.mask;
  const g = e.scene.getObjectByName('cars');
  const out = [];
  const mat = new (e.camera.matrix.constructor)();
  let onGrass = 0, total = 0;
  for (const mesh of g.children) {
    for (let i = 0; i < mesh.count; i++) {
      mesh.getMatrixAt(i, mat);
      const x = mat.elements[12], y = mat.elements[13], z = mat.elements[14];
      const px = Math.floor((x - m.rect[0]) / m.metresPerPx), py = Math.floor((z - m.rect[1]) / m.metresPerPx);
      const r = m.road[py * m.width + px];
      total++;
      if (!r) { onGrass++; if (out.length < 5) out.push([x.toFixed(1), z.toFixed(1), y]); }
    }
  }
  return { total, onGrass, sample: out };
});
console.log(JSON.stringify(info));
await b.close();
