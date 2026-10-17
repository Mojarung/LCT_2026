import { chromium } from '@playwright/test';
const [out] = process.argv.slice(2);
const b = await chromium.launch({ channel: 'chrome', args: ['--use-angle=d3d11', '--enable-gpu', '--ignore-gpu-blocklist'] });
const p = await b.newPage({ viewport: { width: 1600, height: 900 } });
await p.goto('http://localhost:5173/runs/01a0dccf-b370-7389-8cbf-b35ec61f502c/3d#view=20,12,40,-60,-35,fly');
await p.waitForFunction(() => window.__scene, null, { timeout: 240000 });
await p.waitForTimeout(10000);
const info = await p.evaluate(() => {
  const e = window.__scene;
  const res = {};
  for (const name of ['cars', 'city-cars']) {
    const g = e.scene.getObjectByName(name);
    res[name] = g ? g.children.reduce((s, c) => s + c.count, 0) : null;
  }
  const g = e.scene.getObjectByName('city-cars');
  if (g) g.visible = false;
  return res;
});
console.log(JSON.stringify(info));
await p.keyboard.press('h');
await p.waitForTimeout(1500);
await p.screenshot({ path: out });
await b.close();
