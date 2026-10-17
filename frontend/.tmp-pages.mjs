// Scratch: screenshots of every page for the UI audit. Not part of the project.
import { chromium } from '@playwright/test';
const [out, ...urls] = process.argv.slice(2);
const b = await chromium.launch({ channel: 'chrome', args: ['--use-angle=d3d11', '--enable-gpu', '--ignore-gpu-blocklist'] });
const p = await b.newPage({ viewport: { width: 1600, height: 900 } });
for (const [i, u] of urls.entries()) {
  await p.goto(`http://localhost:5173${u}`);
  await p.waitForTimeout(Number(process.env.WAIT ?? 6000));
  await p.screenshot({ path: `${out}-${i}.png`, fullPage: process.env.FULL === '1' });
}
await b.close();
