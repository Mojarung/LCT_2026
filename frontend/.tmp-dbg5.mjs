import { chromium } from '@playwright/test';
const [out] = process.argv.slice(2);
const b = await chromium.launch({ channel: 'chrome', args: ['--use-angle=d3d11', '--enable-gpu', '--ignore-gpu-blocklist'] });
const p = await b.newPage({ viewport: { width: 1600, height: 900 } });
await p.goto('http://localhost:5173/runs/01a0dccf-b370-7389-8cbf-b35ec61f502c/3d#view=20,12,40,-60,-35,fly');
await p.waitForFunction(() => window.__scene, null, { timeout: 240000 });
await p.waitForTimeout(8000);
await p.keyboard.press('h');
for (const [i, name] of ['cars', 'city-cars'].entries()) {
  await p.evaluate((n) => {
    const e = window.__scene;
    for (const k of ['cars', 'city-cars']) { const g = e.scene.getObjectByName(k); if (g) g.visible = k !== n; }
  }, name);
  await p.waitForTimeout(800);
  await p.screenshot({ path: `${out}-${i}.png` });
}
await b.close();
