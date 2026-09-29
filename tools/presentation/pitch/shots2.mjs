// Крупные кадры для слайдов: сети без интерфейса, «до и после» в одной рамке, карточка
// объяснения, перенос посадки с выносками, облёт улицы в 3D.
// Запуск: node tools/presentation/pitch/shots2.mjs  (нужен `green serve`, как для shots.mjs).
// GREEN_EDIT_RUN - отдельный прогон демо-фрагмента: на нём посадку переносят по-настоящему.
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
const editRun = process.env.GREEN_EDIT_RUN;
const only = process.argv.slice(2);
const want = (name) => !only.length || only.includes(name);

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
      localStorage.clear();
      localStorage.setItem('green-theme', t);
    } catch {
      /* без хранилища тема по системе */
    }
  }, theme);
  return context.newPage();
}

async function plan(p, run) {
  await p.goto(`${base}/runs/${run}`);
  await p.waitForSelector('#plan-canvas');
  await p.waitForTimeout(3500);
}

async function layers(p, state) {
  if (!(await p.locator('[aria-label="Условные обозначения"]').isVisible())) {
    await p.getByTitle('Показать или скрыть условные обозначения').click();
    await p.waitForTimeout(500);
  }
  for (const [label, on] of Object.entries(state)) {
    const box = p.getByLabel(label, { exact: false }).first();
    if ((await box.count()) && (await box.isChecked()) !== on) await box.setChecked(on);
  }
  await p.waitForTimeout(600);
}

async function bare(p) {
  for (const name of ['Свернуть панель прогона', 'Свернуть панель состава плана']) {
    const b = p.getByRole('button', { name });
    if (await b.count()) await b.click();
  }
  const legend = p.getByRole('button', { name: 'Скрыть условные обозначения' });
  if (await legend.count()) await legend.click();
  await p.waitForTimeout(800);
}

async function zoom(p, steps) {
  for (let i = 0; i < steps; i += 1) {
    await p.getByRole('button', { name: 'Приблизить' }).click();
    await p.waitForTimeout(250);
  }
  await p.waitForTimeout(1200);
}

async function shot(target, name) {
  await target.screenshot({ path: join(out, `${name}.png`) });
  console.log('снимок', name);
}

const PLAN_OFF = {
  'Посадки плана': false,
  'Газоны плана': false,
  'Зоны допустимости': false,
  'Отклонённые места': false,
  'Слабые места': false,
  'Места, возможные с прикорневым барьером': false,
};

// Сети улицы крупно, без панелей: чем занята земля под газоном
if (want('utilities')) {
  const p = await page('dark');
  await plan(p, street);
  await layers(p, { ...PLAN_OFF, 'Существующие насаждения': false, 'Подписи покрытий': false });
  await bare(p);
  await zoom(p, 3);
  await shot(p, 'utilities');
  await p.close();
}

// Одна рамка до и после: исходные слои, затем они же с планом
if (want('flow')) {
  const p = await page();
  await plan(p, demo);
  await layers(p, PLAN_OFF);
  await bare(p);
  await zoom(p, 2);
  await shot(p, 'flow-before');
  await p.getByRole('button', { name: 'Развернуть панель прогона' }).click();
  await layers(p, { 'Посадки плана': true, 'Газоны плана': true });
  await bare(p);
  await shot(p, 'flow-after');
  await p.close();
}

// Карточка объяснения выбранной посадки: крупно, отдельным кадром панели
if (want('explain')) {
  const p = await page();
  await plan(p, demo);
  await p.locator('#plan-canvas').focus();
  for (let i = 0; i < 40; i += 1) await p.keyboard.press('ArrowRight');
  await p.keyboard.press('Enter');
  await zoom(p, 3);
  await shot(p.locator('aside[aria-label="Состав плана"]'), 'explain-card');
  const left = p.getByRole('button', { name: 'Свернуть панель прогона' });
  if (await left.count()) await left.click();
  await p.waitForTimeout(800);
  await shot(p, 'explain-map');
  await p.close();
}

// Перенос посадки: режим правки, Alt со стрелками, выноски до сетей
if (want('edit') && editRun) {
  const p = await page();
  await plan(p, editRun);
  await p.getByLabel('Переносить и удалять посадки').check();
  await p.locator('#plan-canvas').focus();
  for (let i = 0; i < 40; i += 1) await p.keyboard.press('ArrowRight');
  await p.keyboard.press('Enter');
  await zoom(p, 3);
  // Выбранная посадка в центре карты после приближения: тянем её мышью и снимаем на ходу,
  // пока видны выноски до сетей (кнопку не отпускаем до снимка).
  const box = await p.locator('#plan-canvas').boundingBox();
  const at = { x: Number(process.env.GREEN_EDIT_X ?? 742), y: Number(process.env.GREEN_EDIT_Y ?? 453) };
  await p.mouse.move(at.x, at.y);
  await p.mouse.down();
  for (let i = 1; i <= 12; i += 1) {
    await p.mouse.move(at.x + i * 4, at.y - i * 5);
    await p.waitForTimeout(60);
  }
  await p.waitForTimeout(1200);
  await shot(p, 'edit');
  await p.mouse.up();
  void box;
  await p.close();
}

// Облёт улицы в 3D: камера над крышами вдоль хребта улицы, без панелей
if (want('tour')) {
  const p = await page();
  await p.goto(`${base}/runs/${demo}/3d`);
  await p.waitForSelector('.scene-bar', { timeout: 180000 });
  await p.waitForTimeout(2500);
  await p.keyboard.press('KeyH');
  await p.keyboard.press('KeyT');
  for (const [i, wait] of [4000, 5000, 5000, 5000].entries()) {
    await p.waitForTimeout(wait);
    await shot(p, `scene-tour-${String(i + 1)}`);
  }
  await p.close();
}

await browser.close();
