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
  const cam = e.camera;
  const res = [];
  for (const [sx, sy] of [[1150, 420], [1000, 380], [1250, 470], [600, 400]]) {
    const ndc = { x: (sx / 1600) * 2 - 1, y: -(sy / 900) * 2 + 1 };
    const o = cam.position.clone();
    const d = cam.position.clone().set(ndc.x, ndc.y, 0.5).unproject(cam).sub(o).normalize();
    for (const y0 of [0, -0.15]) {
      const t = (y0 - o.y) / d.y;
      const x = o.x + d.x * t, z = o.z + d.z * t;
      const px = Math.floor((x - m.rect[0]) / m.metresPerPx), py = Math.floor((z - m.rect[1]) / m.metresPerPx);
      res.push([sx, sy, y0, x.toFixed(1), z.toFixed(1), Array.from(ctx.getImageData(px, py, 1, 1).data).join('/'), m.kinds[py*m.width+px]]);
    }
  }
  const g = e.scene.getObjectByName('cars');
  const meshes = g.children.map((c) => [c.name, c.count, c.position.toArray(), c.rotation.toArray().slice(0,3), c.scale.toArray()]);
  return { res, meshes, groupPos: g.position.toArray(), parent: g.parent?.name };
});
console.log(JSON.stringify(info));
await b.close();
