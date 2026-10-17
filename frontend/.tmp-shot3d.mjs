// Scratch: screenshots of the 3D page for visual checks. Not part of the project.
import { chromium } from '@playwright/test';
const [run, prefix, ...views] = process.argv.slice(2);
const base = process.env.BASE ?? 'http://localhost:5173';
const b = await chromium.launch({ channel: 'chrome', args: ['--use-angle=d3d11', '--enable-gpu', '--ignore-gpu-blocklist'] });
const p = await b.newPage({ viewport: { width: 1600, height: 900 } });
const errors = [];
p.on('console', (m) => { if (m.type() === 'error') errors.push(m.text().slice(0, 300)); });
p.on('pageerror', (e) => errors.push(e.message));
for (const [i, view] of (views.length ? views : ['']).entries()) {
  await p.goto('about:blank');
  await p.goto(`${base}/runs/${run}/3d${view ? '#view=' + view : ''}`);
  await p.waitForSelector('.scene-bar', { state: 'attached', timeout: 240000 });
  await p.waitForTimeout(Number(process.env.WAIT ?? 3500));
  await p.keyboard.press('h');
  await p.waitForTimeout(800);
  await p.screenshot({ path: `${prefix}-${i}.png` });
}
console.log(errors.slice(0, 5).join('\n'));
await b.close();
