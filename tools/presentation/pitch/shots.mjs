// Снимки живого сервиса для презентации: node tools/presentation/pitch/shots.mjs
// Нужен `green serve` на GREEN_URL (по умолчанию http://localhost:8021) с прогонами ниже и,
// для фото, с GREEN_PHOTO_MODELS_DIR. Снимки - out/presentation/pitch/shots/*.png, 3200 x 1800.
import { mkdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

import { chromium } from '../../../frontend/node_modules/@playwright/test/index.mjs';

const here = dirname(fileURLToPath(import.meta.url));
const out = join(here, '..', '..', '..', 'out', 'presentation', 'pitch', 'shots');
mkdirSync(out, { recursive: true });

const base = process.env.GREEN_URL ?? 'http://localhost:8021';
const demo = process.env.GREEN_DEMO_RUN ?? '01a0ea97-3423-713b-b04d-28d314b1f21b';
const street = process.env.GREEN_STREET_RUN ?? '01a0dccf-b370-7389-8cbf-b35ec61f502c';
const tree = process.env.GREEN_TREE ?? 'p-1c16064e217f';
const photos = process.argv.includes('--photos');

const browser = await chromium.launch({
  channel: 'chrome',
  args: ['--use-angle=d3d11', '--enable-gpu', '--ignore-gpu-blocklist'],
});

async function page(theme = 'light') {
  const context = await browser.newContext({
    viewport: { width: 1600, height: 900 },
    deviceScaleFactor: 2,
    colorScheme: theme,
  });
  await context.addInitScript((t) => {
    try {
      localStorage.setItem('green-theme', t);
    } catch {
      /* без хранилища - тема по системе, она и так задана */
    }
  }, theme);
  return context.newPage();
}

async function shot(p, name) {
  await p.screenshot({ path: join(out, `${name}.png`) });
  console.log('снимок', name);
}

async function plan(p, run) {
  await p.goto(`${base}/runs/${run}`);
  await p.waitForSelector('#plan-canvas');
  await p.waitForTimeout(3500);
}

// Консоль запуска и реестр прогонов
{
  const p = await page();
  await p.goto(`${base}/`);
  await p.waitForTimeout(2500);
  await shot(p, 'console');
  await p.close();
}

// Рабочее место: весь план фрагмента и выбранная посадка с нормой и выносками
{
  const p = await page();
  await plan(p, demo);
  await shot(p, 'plan-demo');
  await p.locator('#plan-canvas').focus();
  for (let i = 0; i < 40; i += 1) await p.keyboard.press('ArrowRight');
  await p.keyboard.press('Enter');
  for (let i = 0; i < 3; i += 1) {
    await p.getByRole('button', { name: 'Приблизить' }).click();
    await p.waitForTimeout(250);
  }
  await p.waitForTimeout(1500);
  await shot(p, 'plan-selected');
  await p.close();
}

// Целая улица каталога в светлой и тёмной теме
for (const theme of ['light', 'dark']) {
  const p = await page(theme);
  await plan(p, street);
  await shot(p, `plan-street-${theme}`);
  await p.close();
}

// Уточнение объектов чертежа
{
  const p = await page();
  await p.goto(`${base}/runs/${demo}/review`);
  await p.waitForTimeout(4000);
  await shot(p, 'review');
  await p.close();
}

// 3D: общий вид без панелей, галерея улицы и галерея посадки
{
  const p = await page();
  await p.goto(`${base}/runs/${demo}/3d`);
  await p.waitForSelector('.scene-bar', { timeout: 180000 });
  await p.waitForTimeout(2500);
  await p.keyboard.press('KeyH');
  await p.waitForTimeout(1200);
  await shot(p, 'scene3d');
  await p.close();
}
for (const [query, name] of [
  ['shots=street', 'gallery-street'],
  [`plant=${tree}`, 'gallery-plant'],
]) {
  const p = await page();
  await p.goto(`${base}/runs/${demo}/3d?${query}`);
  await p.waitForSelector('.gallery-card img', { timeout: 180000 });
  await p.waitForTimeout(1200);
  await shot(p, name);
  if (photos) {
    // Кадр улицы - по плану, кадр посадки - с фоном и деревьями: оба режима на слайд.
    if (name === 'gallery-plant') await p.locator('.gallery-scenery input').check();
    await p.locator('.gallery-card').first().getByRole('button', { name: 'фото' }).click();
    await p.waitForTimeout(1500);
  }
  await p.close();
}

// База моделей растений и Swagger
{
  const p = await page();
  await p.goto(`${base}/models`);
  await p.waitForTimeout(3000);
  await shot(p, 'models');
  await p.goto(`${base}/docs`);
  await p.waitForTimeout(3000);
  await shot(p, 'swagger');
  await p.close();
}

await browser.close();
