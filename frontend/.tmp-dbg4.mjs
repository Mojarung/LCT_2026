import { chromium } from '@playwright/test';
const b = await chromium.launch({ channel: 'chrome', args: ['--use-angle=d3d11', '--enable-gpu', '--ignore-gpu-blocklist'] });
const p = await b.newPage({ viewport: { width: 1600, height: 900 } });
await p.goto('http://localhost:5173/runs/01a0dccf-b370-7389-8cbf-b35ec61f502c/3d#view=20,12,40,-60,-35,fly');
await p.waitForFunction(() => window.__scene, null, { timeout: 240000 });
await p.waitForTimeout(6000);
const info = await p.evaluate(() => {
  const e = window.__scene;
  const m = e.mask;
  const ctx = m.texture.image.getContext('2d');
  const g = e.scene.getObjectByName('cars');
  const mat = new (e.camera.matrix.constructor)();
  const out = [];
  for (const mesh of g.children) {
    for (let i = 0; i < mesh.count; i++) {
      mesh.getMatrixAt(i, mat);
      const x = mat.elements[12], z = mat.elements[14];
      if (Math.hypot(x - 20, z - 40) > 45) continue;
      const px = Math.floor((x - m.rect[0]) / m.metresPerPx), py = Math.floor((z - m.rect[1]) / m.metresPerPx);
      const d = ctx.getImageData(px, py, 1, 1).data;
      out.push([x.toFixed(1), z.toFixed(1), m.road[py * m.width + px], Array.from(d).join('/')]);
    }
  }
  return { rect: m.rect, mpp: m.metresPerPx, w: m.width, h: m.height, cw: m.texture.image.width, out };
});
console.log(JSON.stringify(info));
await b.close();
