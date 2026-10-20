// Снимки живого сервиса для презентации: node tools/presentation/pitch/shots.mjs [имена кадров]
// Нужен сервис на GREEN_URL (по умолчанию http://localhost:8000) с прогонами ниже:
// GREEN_STREET_RUN - целая улица каталога (Кустанайская), GREEN_DEMO_RUN - фрагмент Берзарина.
// Снимки - out/presentation/pitch/shots/*.png, 3200 x 1800 (окно 1920 x 1080, плотность 5/3).
// Фото ИИ: с флагом --photos кадр 3D-вида уходит в генератор, готовое фото сохраняется как
// photo-ai.jpg; без флага берётся последнее готовое фото прогона, если оно есть.
import { mkdirSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

import { chromium } from '../../../frontend/node_modules/@playwright/test/index.mjs';

const here = dirname(fileURLToPath(import.meta.url));
const out = join(here, '..', '..', '..', 'out', 'presentation', 'pitch', 'shots');
mkdirSync(out, { recursive: true });

const base = process.env.GREEN_URL ?? 'http://localhost:8000';
const street = process.env.GREEN_STREET_RUN;
const demo = process.env.GREEN_DEMO_RUN ?? street;
const photos = process.argv.includes('--photos');
const only = process.argv.slice(2).filter((a) => !a.startsWith('--'));
const want = (name) => !only.length || only.includes(name);
if (!street) throw new Error('GREEN_STREET_RUN: id прогона улицы из GET /api/v1/runs');

const browser = await chromium.launch({
  channel: 'chrome',
  args: ['--use-angle=d3d11', '--enable-gpu', '--ignore-gpu-blocklist'],
});

async function page(theme = 'light') {
  const context = await browser.newContext({
    viewport: { width: 1920, height: 1080 },
    deviceScaleFactor: 5 / 3,
    colorScheme: theme,
  });
  await context.addInitScript((t) => {
    try {
      localStorage.clear();
      localStorage.setItem('green-theme', t);
    } catch {
      /* без хранилища тема по системе, она и так задана */
    }
  }, theme);
  return context.newPage();
}

async function shot(target, name) {
  await target.screenshot({ path: join(out, `${name}.png`) });
  console.log('снимок', name);
}

async function plan(p, run) {
  await p.goto(`${base}/runs/${run}`);
  await p.waitForSelector('#plan-canvas', { timeout: 180000 });
  await p.waitForTimeout(4000);
}

async function tab(p, name) {
  await p.getByRole('group', { name: 'Раздел плана' }).getByRole('button', { name }).click();
  await p.waitForTimeout(600);
}

// Слои карты - флажки вкладки «Легенда»; после настройки вкладка возвращается к посадкам.
async function layers(p, state) {
  await tab(p, 'Легенда');
  const legend = p.getByRole('complementary', { name: 'Условные обозначения' });
  for (const [label, on] of Object.entries(state)) {
    const box = legend.getByRole('checkbox', { name: label, exact: false }).first();
    if ((await box.count()) && (await box.isChecked()) !== on) await box.setChecked(on);
  }
  await p.waitForTimeout(600);
  await tab(p, 'Посадки');
}

async function collapse(p, ...names) {
  for (const name of names) {
    const b = p.getByRole('button', { name });
    if (await b.count()) await b.click();
  }
  await p.waitForTimeout(900);
}

async function zoom(p, steps) {
  for (let i = 0; i < steps; i += 1) {
    await p.getByRole('button', { name: 'Приблизить' }).click();
    await p.waitForTimeout(250);
  }
  await p.waitForTimeout(1500);
}

// Посадка по счёту с клавиатуры: стрелки перебирают посадки, Enter выбирает.
async function pick(p, steps) {
  await p.locator('#plan-canvas').focus();
  for (let i = 0; i < steps; i += 1) await p.keyboard.press('ArrowRight');
  await p.keyboard.press('Enter');
  await p.waitForTimeout(1500);
  await p.locator('#plan-canvas').evaluate((el) => el.blur());
  await p.waitForTimeout(400);
}

const PLAN_OFF = {
  'Посадки плана': false,
  'Газоны плана': false,
  'Зоны допустимости': false,
  'Отклонённые места': false,
  'Слабые места': false,
  'Места, возможные с прикорневым барьером': false,
};
const PANELS = ['Свернуть панель прогона', 'Свернуть панель состава плана'];
const pickSteps = Number(process.env.GREEN_PICK ?? 40);

// Главная: форма запуска, реестр прогонов, коллаж результата
if (want('console')) {
  const p = await page();
  await p.goto(`${base}/`);
  await p.waitForTimeout(7000);
  await shot(p, 'console');
  await p.close();
}

// Рабочее место: план улицы, выбранная посадка и её объяснение в правой панели
if (want('workspace')) {
  const p = await page();
  await plan(p, street);
  await shot(p, 'plan-street-light');
  await pick(p, pickSteps);
  await zoom(p, 2);
  await shot(p, 'workspace');
  await shot(p.getByRole('complementary', { name: 'Состав плана' }), 'explain-card');
  await collapse(p, 'Свернуть панель прогона');
  await shot(p, 'explain-map');
  await p.close();
}

// Сети улицы крупно, тёмная тема, без плана и панелей
if (want('utilities')) {
  const p = await page('dark');
  await plan(p, street);
  await layers(p, {
    ...PLAN_OFF,
    'Существующие насаждения': false,
    'Подписи покрытий': false,
    'Газон и покрытия': false,
  });
  await collapse(p, ...PANELS);
  await zoom(p, 3);
  await shot(p, 'utilities');
  await p.close();
}

// Одна рамка до и после: исходные слои, затем они же с планом
if (want('flow')) {
  const p = await page();
  await plan(p, demo);
  await layers(p, PLAN_OFF);
  await collapse(p, ...PANELS);
  await zoom(p, 2);
  await shot(p, 'flow-before');
  await p.getByRole('button', { name: 'Развернуть панель состава плана' }).click();
  await layers(p, { 'Посадки плана': true, 'Газоны плана': true });
  await collapse(p, 'Свернуть панель состава плана');
  await shot(p, 'flow-after');
  await p.close();
}

// Уточнение объектов чертежа: таблица классов, подсказки модели по именам слоёв
if (want('review')) {
  const p = await page();
  await p.goto(`${base}/runs/${process.env.GREEN_REVIEW_RUN ?? street}/review`);
  await p.waitForTimeout(6000);
  await shot(p, 'review');
  await p.close();
}

async function scene(p, run) {
  await p.goto(`${base}/runs/${run}/3d`);
  await p.waitForSelector('.scene-bar', { timeout: 240000 });
  await p.waitForTimeout(9000);
}

async function hour(p, value) {
  await p.getByRole('slider', { name: /Время суток/ }).fill(String(value));
  await p.waitForTimeout(3500);
}

// 3D: общий вид днём и вечером, без панелей; по желанию - фото ИИ по дневному кадру
if (want('scene')) {
  const p = await page();
  await scene(p, street);
  if (process.env.GREEN_VIEW) {
    await p.evaluate((h) => {
      window.location.hash = h;
    }, process.env.GREEN_VIEW);
    await p.waitForTimeout(4000);
  }
  // Облёт по хребту улицы: камера останавливается там, где её застала пауза
  const tour = Number(process.env.GREEN_TOUR_MS ?? 0);
  if (tour) {
    await p.keyboard.press('KeyT');
    await p.waitForTimeout(tour);
    await p.keyboard.press('KeyT');
    await p.waitForTimeout(1500);
  }
  await hour(p, 12);
  if (photos) {
    await p.getByRole('button', { name: 'Фото ИИ' }).click();
    await p.waitForTimeout(3000);
  }
  await p.keyboard.press('KeyH');
  await p.waitForTimeout(1500);
  await shot(p, 'scene3d');
  await p.keyboard.press('KeyH');
  await hour(p, Number(process.env.GREEN_NIGHT_HOUR ?? 21));
  await p.keyboard.press('KeyH');
  await p.waitForTimeout(2500);
  await shot(p, 'scene-night');
  await p.close();
}

// Готовое фото ИИ прогона: последнее по времени, файл photo (4K JPEG)
if (want('photo')) {
  const api = `${base}/api/v1/runs/${street}/photos`;
  const deadline = Date.now() + 15 * 60 * 1000;
  let done = null;
  while (Date.now() < deadline) {
    const list = await (await fetch(api)).json();
    const ready = list.photos.filter((ph) => ph.state === 'succeeded' || ph.state === 'done');
    if (ready.length) {
      done = ready.at(-1);
      break;
    }
    if (!list.photos.length || !photos) break;
    await new Promise((r) => setTimeout(r, 10000));
  }
  if (done) {
    // Без апскейлера сервис отдаёт фото как PNG: расширение - по типу ответа.
    for (const [kind, name] of [
      ['photo', 'photo-ai'],
      ['source', 'photo-ai-src'],
    ]) {
      const res = await fetch(`${api}/${done.id}/${kind}`);
      if (res.ok) {
        const ext = (res.headers.get('content-type') ?? '').includes('png') ? 'png' : 'jpg';
        writeFileSync(join(out, `${name}.${ext}`), Buffer.from(await res.arrayBuffer()));
        console.log('фото', kind, done.id);
      }
    }
  } else console.log('фото ИИ нет: снимите с --photos или сделайте в 3D-виде');
}

// База моделей растений и Swagger
if (want('models')) {
  const p = await page();
  await p.goto(`${base}/models`);
  await p.waitForTimeout(4000);
  await shot(p, 'models');
  await p.goto(`${base}/docs`);
  await p.waitForTimeout(4000);
  await shot(p, 'swagger');
  await p.close();
}

await browser.close();
