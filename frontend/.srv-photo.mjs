import { chromium } from '@playwright/test';
const base = 'http://localhost:8080', run = '01a0ed53-801f-736b-a612-bd8d51b409c8';
const b = await chromium.launch({ channel: 'chrome', args: ['--use-angle=d3d11', '--enable-gpu', '--ignore-gpu-blocklist'] });
const p = await b.newPage({ viewport: { width: 1600, height: 900 } });
await p.goto(`${base}/runs/${run}/3d`);
await p.waitForSelector('.scene-media', { timeout: 240000 });
await p.waitForTimeout(3000);
await p.locator('.media-actions').getByRole('button', { name: /фото ИИ/ }).click();
const t0 = Date.now();
let last;
for (;;) {
  await p.waitForTimeout(5000);
  const list = (await (await fetch(`${base}/api/v1/runs/${run}/photos`)).json()).photos;
  last = list[0];
  if (last && (last.state === 'succeeded' || last.state === 'failed')) break;
  if (Date.now() - t0 > 600000) break;
}
console.log(last?.state, last?.seconds, last?.upscaled, last?.error, last?.width, last?.height);
await b.close();
