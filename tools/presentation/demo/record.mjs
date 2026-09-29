// Запись демо сервиса: Full HD 60 к/с, этапы с подписями, крупные планы средствами страницы.
//
// Chrome на весь второй монитор (1920 x 1080, киоск), ffmpeg снимает этот монитор через
// Desktop Duplication (ddagrab) и кодирует на видеокарте. Подписи этапов, курсор и приближение
// рисует сама страница: текст при приближении остаётся резким, а не растянутым кадром.
// Долгие ожидания (расчёт, фото нейросетью) отмечаются и при монтаже ускоряются или
// вырезаются: node tools/presentation/demo/record.mjs, затем --edit (только монтаж).
//
// Нужен `green serve` на GREEN_URL (по умолчанию :8021) с GREEN_PHOTO_MODELS_DIR, чтобы
// фото работало, и снимки LibreCAD в out/presentation/demo (docker/cadcheck, разд. 5.6).
import { spawn } from 'node:child_process';
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

import { chromium } from '../../../frontend/node_modules/@playwright/test/index.mjs';

const here = dirname(fileURLToPath(import.meta.url));
const out = join(here, '..', '..', '..', 'out', 'presentation', 'demo');
mkdirSync(out, { recursive: true });
const base = process.env.GREEN_URL ?? 'http://localhost:8021';
const MONITOR = Number(process.env.DEMO_MONITOR ?? 1); // ddagrab output_idx
const POSITION = process.env.DEMO_POSITION ?? '3440,121'; // левый верхний угол монитора
const RAW = join(out, 'raw.mkv'); // MKV переживает обрыв записи
const MARKS = join(out, 'marks.json');
const FINAL = join(out, 'green-demo.mp4');
// Полная улица для 3D и фото и ракурс дорожки с людьми (подобран по сцене прогона).
const SCENE_RUN = process.env.GREEN_SCENE_RUN ?? '01a0dccf-b370-7389-8cbf-b35ec61f502c';
const SCENE_VIEW = process.env.GREEN_SCENE_VIEW ?? 'view=-130.4,7.5,-220.6,-150.0,-12,fly';

// --------------------------------------------------------------------------- слой демо в странице

const overlay = () => {
  const style = `
#demo-cursor{position:fixed;left:0;top:0;z-index:2147483647;pointer-events:none;
  transition:transform 40ms linear;will-change:transform}
#demo-ring{position:fixed;left:0;top:0;width:44px;height:44px;margin:-22px 0 0 -22px;
  border-radius:50%;border:3px solid #FF0053;z-index:2147483646;pointer-events:none;opacity:0}
#demo-ring.on{animation:demo-ring .5s ease-out}
@keyframes demo-ring{from{opacity:.9;transform:var(--at) scale(.4)}to{opacity:0;transform:var(--at) scale(1.3)}}
#demo-cap{position:fixed;left:50%;top:22px;z-index:2147483645;pointer-events:none;
  transform:translate(-50%,-14px);opacity:0;transition:opacity .45s,transform .45s;
  font:600 23px/1.35 Montserrat,'Plex',system-ui,sans-serif;color:#fff;
  background:rgba(28,29,34,.9);padding:14px 26px 16px;border-radius:14px;max-width:1240px;
  box-shadow:0 12px 34px rgba(0,0,0,.35);text-align:center}
#demo-cap.on{opacity:1;transform:translate(-50%,0)}
#demo-cap b{display:block;font-size:14px;letter-spacing:.1em;text-transform:uppercase;
  color:#FF6A95;margin-bottom:5px}`;
  const install = () => {
    if (document.getElementById('demo-cap')) return;
    const css = document.createElement('style');
    css.textContent = style;
    document.documentElement.append(css);
    const cursor = document.createElement('div');
    cursor.id = 'demo-cursor';
    cursor.innerHTML =
      '<svg width="26" height="30" viewBox="0 0 26 30"><path d="M2 2 L2 24 L8 18 L12.5 28 L16.5 26.2 L12 16.5 L20 16.5 Z" fill="#1C1D22" stroke="#fff" stroke-width="2" stroke-linejoin="round"/></svg>';
    const ring = document.createElement('div');
    ring.id = 'demo-ring';
    const cap = document.createElement('div');
    cap.id = 'demo-cap';
    document.documentElement.append(cursor, ring, cap);
    const at = JSON.parse(sessionStorage.getItem('demo-at') ?? '[960,540]');
    cursor.style.transform = `translate(${at[0]}px,${at[1]}px)`;
    const saved = JSON.parse(sessionStorage.getItem('demo-cap') ?? 'null');
    if (saved) {
      cap.innerHTML = `<b>${saved[0]}</b>${saved[1]}`;
      cap.classList.add('on');
    }
    addEventListener(
      'mousemove',
      (e) => {
        cursor.style.transform = `translate(${e.clientX}px,${e.clientY}px)`;
        sessionStorage.setItem('demo-at', JSON.stringify([e.clientX, e.clientY]));
      },
      true,
    );
    addEventListener(
      'mousedown',
      (e) => {
        ring.style.setProperty('--at', `translate(${e.clientX}px,${e.clientY}px)`);
        ring.style.transform = `translate(${e.clientX}px,${e.clientY}px)`;
        ring.classList.remove('on');
        void ring.offsetWidth;
        ring.classList.add('on');
      },
      true,
    );
  };
  window.__cap = (step, text) => {
    install();
    const cap = document.getElementById('demo-cap');
    if (!step) {
      sessionStorage.removeItem('demo-cap');
      cap.classList.remove('on');
      return;
    }
    sessionStorage.setItem('demo-cap', JSON.stringify([step, text]));
    cap.classList.remove('on');
    setTimeout(() => {
      cap.innerHTML = `<b>${step}</b>${text}`;
      cap.classList.add('on');
    }, 250);
  };
  // Приближение области экрана: масштаб body, слой демо (он вне body) остаётся на месте.
  window.__zoom = (x, y, w, h, ms = 900) => {
    const s = Math.min(innerWidth / w, innerHeight / h);
    const body = document.body;
    body.style.transformOrigin = '0 0';
    body.style.transition = `transform ${ms}ms cubic-bezier(.22,.7,.2,1)`;
    const tx = Math.min(
      0,
      Math.max(innerWidth - innerWidth * s, -x * s + (innerWidth - w * s) / 2),
    );
    const ty = Math.min(
      0,
      Math.max(innerHeight - innerHeight * s, -y * s + (innerHeight - h * s) / 2),
    );
    body.style.transform = `translate(${tx}px,${ty}px) scale(${s})`;
  };
  window.__unzoom = (ms = 800) => {
    document.body.style.transition = `transform ${ms}ms cubic-bezier(.22,.7,.2,1)`;
    document.body.style.transform = '';
  };
  if (document.readyState === 'loading') addEventListener('DOMContentLoaded', install);
  else install();
};

// --------------------------------------------------------------------------- съёмка

function startCapture() {
  const ff = spawn(
    'ffmpeg',
    [
      '-hide_banner',
      '-y',
      '-f',
      'lavfi',
      '-i',
      `ddagrab=output_idx=${MONITOR}:framerate=60:draw_mouse=0`,
      '-c:v',
      'h264_nvenc',
      '-preset',
      'p5',
      '-rc',
      'vbr',
      '-cq',
      '16',
      '-b:v',
      '0',
      RAW,
    ],
    { stdio: ['pipe', 'ignore', 'pipe'] },
  );
  const started = new Promise((resolve) => {
    ff.stderr.on('data', (chunk) => {
      if (String(chunk).includes('frame=')) resolve(Date.now());
    });
  });
  const done = new Promise((resolve) => ff.on('close', resolve));
  return {
    started,
    stop: async () => {
      ff.stdin.write('q');
      await done;
    },
  };
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function record() {
  const browser = await chromium.launch({
    channel: 'chrome',
    headless: false,
    ignoreDefaultArgs: ['--enable-automation'],
    args: [
      `--window-position=${POSITION}`,
      '--window-size=1920,1080',
      '--kiosk',
      '--force-device-scale-factor=1',
      '--disable-infobars',
      '--hide-scrollbars',
      '--use-angle=d3d11',
      '--enable-gpu',
      '--ignore-gpu-blocklist',
      '--autoplay-policy=no-user-gesture-required',
    ],
  });
  const context = await browser.newContext({ viewport: null, acceptDownloads: false });
  await context.addInitScript(overlay);
  await context.addInitScript(() => {
    try {
      localStorage.setItem('green-theme', 'light');
    } catch {
      /* без хранилища - тема по системе */
    }
  });
  const page = await context.newPage();
  // --kiosk из Playwright не срабатывает: окно разворачивается на весь монитор через CDP.
  const cdp = await context.newCDPSession(page);
  const { windowId } = await cdp.send('Browser.getWindowForTarget');
  await cdp.send('Browser.setWindowBounds', { windowId, bounds: { windowState: 'fullscreen' } });
  await sleep(1500);
  const marks = {};
  let t0 = 0;
  const mark = (name) => {
    marks[name] = (Date.now() - t0) / 1000;
  };
  const cap = (step, text) => page.evaluate(([s, t]) => window.__cap(s, t), [step, text]);
  const zoom = (x, y, w, h) =>
    page.evaluate(([a, b, c, d]) => window.__zoom(a, b, c, d), [x, y, w, h]);
  const unzoom = () => page.evaluate(() => window.__unzoom());
  const glide = async (locator, { click = true } = {}) => {
    await locator.scrollIntoViewIfNeeded().catch(() => {});
    const box = await locator.boundingBox();
    if (!box) throw new Error('нет элемента для курсора');
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2, { steps: 28 });
    await sleep(250);
    if (click) await page.mouse.down().then(() => page.mouse.up());
    await sleep(350);
  };
  const boxOf = async (locator) => {
    const box = await locator.boundingBox();
    if (!box) throw new Error('нет элемента');
    return box;
  };

  // Титул: пока он на экране, стартует запись.
  const intro = pathToFileURL(join(out, 'intro.html')).href;
  writeFileSync(join(out, 'intro.html'), INTRO);
  await page.goto(intro);
  await sleep(1500);
  const size = await page.evaluate(() => [innerWidth, innerHeight]);
  if (size[0] !== 1920 || size[1] !== 1080) {
    await browser.close();
    throw new Error(`окно не на весь монитор: ${size.join('x')}, запись не начата`);
  }
  const capture = startCapture();
  t0 = await capture.started;
  try {
    await sleep(4500);

    // 1. Вход
    await page.goto(`${base}/`);
    await page.waitForLoadState('networkidle');
    await sleep(800);
    await cap(
      '1 · Вход',
      'Встроенный фрагмент улицы Берзарина: подоснова Мосгеотреста с сетями, 12 694 объекта',
    );
    await sleep(3500);
    const launch = page.getByRole('button', { name: 'Запустить на встроенном участке' });
    await glide(launch);

    // 2. Расчёт
    await page.waitForURL(/\/runs\/[0-9a-f-]+$/, { timeout: 60000 });
    const runId = page.url().split('/runs/')[1];
    await cap(
      '2 · Расчёт по нормам',
      'Чтение без потерь, карта покрытий, места посадки, подбор вида, независимая проверка',
    );
    mark('run_start');
    for (;;) {
      const state = await page.evaluate(
        async (id) => (await (await fetch(`/api/v1/runs/${id}`)).json()).state,
        runId,
      );
      if (state === 'succeeded' || state === 'failed') break;
      await sleep(1000);
    }
    await page.waitForSelector('#plan-canvas');
    await sleep(2500);
    mark('run_end');

    // 3. План
    await cap(
      '3 · План на отдельных слоях',
      'Деревья, кустарник и газоны на слоях GREEN_*. Исходные слои чертежа не меняются',
    );
    await sleep(4000);
    const zoomIn = page.getByRole('button', { name: 'Приблизить' });
    await glide(zoomIn);
    await sleep(600);
    await glide(zoomIn);
    await sleep(2500);
    await cap(
      '3 · План на отдельных слоях',
      'Подземные сети на карте: у каждой свой цвет, отступ от неё проверяется для каждой ямы',
    );
    await sleep(4500);

    // 4. Объяснение посадки
    const canvas = page.locator('#plan-canvas');
    await canvas.focus();
    for (let i = 0; i < 40; i += 1) await page.keyboard.press('ArrowRight');
    await page.keyboard.press('Enter');
    await glide(zoomIn);
    await sleep(1500);
    await cap(
      '4 · Объяснение посадки',
      'Замер до ближайшей сети, норма, акт и пункт с дословной цитатой. Без языковой модели',
    );
    await sleep(2500);
    const detail = page.getByRole('complementary', { name: 'Состав плана' });
    const card = await boxOf(detail);
    await page.mouse.move(card.x + card.width / 2, card.y + 200, { steps: 30 });
    await zoom(card.x - 20, card.y, card.width + 40, Math.min(card.height, 620));
    await sleep(6500);
    await unzoom();
    await sleep(1500);

    // 5. Правка
    await cap(
      '5 · Правка в браузере',
      'Перенос посадки проверяется теми же нормами. Место ближе нормы сервис не примет',
    );
    const editing = page.getByLabel('Переносить и удалять посадки');
    await glide(editing);
    await sleep(1200);
    await canvas.focus();
    await page.keyboard.down('Alt');
    for (let i = 0; i < 5; i += 1) {
      await page.keyboard.press('Shift+ArrowLeft');
      await sleep(380);
    }
    await page.keyboard.up('Alt');
    await sleep(3500);
    const message = page.locator('.edit-message');
    const bar = await boxOf(page.locator('#edit-bar'));
    await zoom(bar.x - 10, bar.y - 60, bar.width + 20, bar.height + 120);
    await sleep(4500);
    await unzoom();
    await sleep(1000);
    // Если перенос не прошёл проверку плана (шаг до соседей), посадка возвращается на место:
    // пересобирается только план без нарушений.
    const gate = await page.evaluate(
      async (id) => (await (await fetch(`/api/v1/runs/${id}/draft`)).json()).quality?.gate ?? '',
      runId,
    );
    if (gate.startsWith('После правки')) {
      await cap(
        '5 · Правка в браузере',
        'План с этим переносом не проходит проверку: посадку возвращаем на место',
      );
      await sleep(2500);
      await canvas.focus();
      await page.keyboard.down('Alt');
      for (let i = 0; i < 5; i += 1) {
        await page.keyboard.press('Shift+ArrowRight');
        await sleep(380);
      }
      await page.keyboard.up('Alt');
      await sleep(3500);
    }
    const rebuild = page.locator('#rebuild');
    if (await rebuild.isVisible().catch(() => false)) {
      await cap(
        '5 · Правка в браузере',
        'Пересборка переписывает DXF и объяснения по новому плану',
      );
      await glide(rebuild);
      await page
        .waitForFunction(() => !document.querySelector('#rebuild'), null, { timeout: 120000 })
        .catch(() => {});
      await sleep(2000);
    } else {
      console.log('правка:', await message.textContent());
    }

    // 6. Выгрузка
    await cap(
      '6 · Выгрузка',
      'DXF со слоями GREEN_*, нормы в CSV и отчёт: у каждой посадки определяющая норма и пункт акта',
    );
    const back = page.getByRole('button', { name: /К плану|к составу плана/ }).first();
    if (await back.isVisible().catch(() => false)) await glide(back);
    await sleep(1000);
    const dxf = page.getByRole('link', { name: /Скачать план DXF|Скачать DXF/ }).first();
    await glide(dxf, { click: false });
    await sleep(2500);
    const reportLink = page.getByRole('link', { name: /Отчёт по посадкам/ }).first();
    let reportPage = null;
    if (await reportLink.isVisible().catch(() => false)) {
      const popup = context.waitForEvent('page');
      await glide(reportLink);
      reportPage = await popup;
    } else {
      reportPage = await context.newPage();
      await reportPage.goto(`${base}/api/v1/runs/${runId}/artifacts/report.html`);
    }
    await reportPage.waitForLoadState('load');
    await reportPage.bringToFront();
    await sleep(1500);
    await reportPage.evaluate(
      ([s, t]) => window.__cap(s, t),
      [
        '6 · Отчёт по посадкам',
        'Каждая посадка: вид, определяющая норма, запас в метрах, акт и пункт',
      ],
    );
    await sleep(3000);
    await reportPage.mouse.wheel(0, 900);
    await sleep(1800);
    await reportPage.evaluate(() => window.__zoom(0, 0, 1100, 620));
    await sleep(5000);
    await reportPage.evaluate(() => window.__unzoom());
    await sleep(1200);
    await reportPage.close();
    await page.bringToFront();

    // 7. DXF в CAD под Linux
    const cadPage = await context.newPage();
    writeFileSync(join(out, 'cad.html'), CAD);
    await cadPage.goto(pathToFileURL(join(out, 'cad.html')).href);
    await cadPage.bringToFront();
    await cadPage.evaluate(
      ([s, t]) => window.__cap(s, t),
      [
        '7 · DXF в CAD под Linux',
        'LibreCAD 2.2 в Ubuntu 26.04: план поверх подосновы, исходные слои на месте',
      ],
    );
    await sleep(5000);
    await cadPage.evaluate(() => window.__zoom(1100, 60, 860, 484));
    await cadPage.evaluate(
      ([s, t]) => window.__cap(s, t),
      [
        '7 · DXF в CAD под Linux',
        'Результат на 11 слоях GREEN_*: каждый включается и выключается отдельно',
      ],
    );
    await sleep(5500);
    await cadPage.evaluate(() => window.__unzoom());
    await sleep(900);
    await cadPage.evaluate(() => document.body.classList.add('verify'));
    await cadPage.evaluate(
      ([s, t]) => window.__cap(s, t),
      [
        '7 · Проверка сохранности',
        'green verify: все 12 694 исходных объекта без изменений, вне слоёв GREEN_* ничего не добавлено',
      ],
    );
    await sleep(6500);
    await cadPage.close();
    await page.bringToFront();

    // 8. 3D-вид
    // 3D и фото - на полной улице пилота, посчитанной заранее (docs/demo.md): у фрагмента
    // вокруг пустой газон, а у Кустанайской дома, тротуары и люди.
    await page.goto(`${base}/runs/${SCENE_RUN}/3d#${SCENE_VIEW}`);
    await page.waitForSelector('.scene-bar', { timeout: 240000 });
    await sleep(2500);
    await cap(
      '8 · 3D-вид: Кустанайская улица целиком',
      'Прогон полной улицы пилота посчитан заранее. Здания по этажности из подписей, кроны по виду и возрасту',
    );
    const plants = page.locator('summary', { hasText: 'Посадки' }).first();
    if (await plants.count()) await glide(plants);
    await glide(page.getByRole('radio', { name: '25 лет' }));
    await page.locator('input[type=range]').first().fill('18');
    await sleep(1500);
    await page.mouse.move(960, 700, { steps: 20 });
    await page.keyboard.press('KeyT');
    await sleep(10000);
    await page.keyboard.press('KeyT');
    await page.evaluate((h) => {
      window.location.hash = h;
    }, SCENE_VIEW);
    await sleep(2500);
    await cap(
      '8 · 3D-вид: Кустанайская улица целиком',
      'Люди на тротуарах, сезон и время суток меняются на пульте',
    );
    await glide(page.getByRole('radio', { name: 'осень' }));
    await sleep(3500);
    await glide(page.getByRole('radio', { name: 'лето' }));
    await sleep(2000);

    // 9. Фото нейросетью
    await cap(
      '9 · Фото по кадру 3D-вида',
      'Qwen-Image-2.1 на локальной видеокарте 6 ГБ перерисовывает кадр: деревья стоят там же, где в плане',
    );
    const photosBefore = await page.evaluate(
      async (id) => (await (await fetch(`/api/v1/runs/${id}/photos`)).json()).photos.length,
      SCENE_RUN,
    );
    const photoButton = page.locator('.media-actions').getByRole('button', { name: /фото ИИ/ });
    await glide(photoButton);
    const media = await boxOf(page.locator('.scene-media'));
    await zoom(media.x, media.y, media.width + 40, Math.min(media.height, 720));
    await sleep(4000);
    mark('photo_start');
    for (;;) {
      const photos = await page.evaluate(
        async (id) => (await (await fetch(`/api/v1/runs/${id}/photos`)).json()).photos,
        SCENE_RUN,
      );
      const newest = photos.sort((a, b) => b.created_at.localeCompare(a.created_at))[0];
      const done = newest?.state === 'succeeded' || newest?.state === 'failed';
      if (photos.length > photosBefore && done) break;
      await sleep(2000);
    }
    await sleep(3500);
    mark('photo_end');
    await unzoom();
    await sleep(1200);
    await glide(page.locator('.media-open').first());
    await sleep(4500);
    const frameSide = page.getByRole('radio', { name: /3D-кадр/ });
    if (await frameSide.count()) {
      await glide(frameSide);
      await sleep(2500);
      await glide(page.getByRole('radio', { name: /^фото/ }));
      await sleep(3000);
    }
    await page.keyboard.press('Escape');
    await sleep(1200);

    // 10. API
    await page.goto(`${base}/docs`);
    await page.waitForLoadState('networkidle');
    await cap(
      '10 · HTTP API',
      'Тот же сценарий через API: OpenAPI и Swagger без внешней сети, запуск - docker compose up',
    );
    await sleep(6000);
    await page.mouse.wheel(0, 500);
    await sleep(3500);
    await page.goto(pathToFileURL(join(out, 'intro.html')).href + '#end');
    await sleep(5000);
  } finally {
    mark('end');
    await capture.stop();
    writeFileSync(MARKS, JSON.stringify(marks, null, 2));
    await browser.close();
  }
  console.log('запись', RAW, marks);
}

// --------------------------------------------------------------------------- монтаж

function edit() {
  const marks = JSON.parse(readFileSync(MARKS, 'utf8'));
  // Расчёт идёт втрое быстрее, ожидание фото вырезается (по 2 с остаётся с каждой стороны).
  const segments = [
    [0, marks.run_start + 2, 1],
    [marks.run_start + 2, marks.run_end - 1, 3],
    [marks.run_end - 1, marks.photo_start + 2, 1],
    [marks.photo_end - 2, marks.end + 1, 1],
  ].filter(([a, b]) => b > a);
  const parts = segments.map(
    ([a, b, speed], i) =>
      `[0:v]trim=start=${a.toFixed(3)}:end=${b.toFixed(3)},setpts=(PTS-STARTPTS)/${speed}[v${i}]`,
  );
  const graph = `${parts.join(';')};${segments.map((_, i) => `[v${i}]`).join('')}concat=n=${segments.length}:v=1:a=0,fps=60,format=yuv420p[out]`;
  const args = [
    '-hide_banner',
    '-y',
    '-i',
    RAW,
    '-filter_complex',
    graph,
    '-map',
    '[out]',
    '-c:v',
    'h264_nvenc',
    '-preset',
    'p7',
    '-rc',
    'vbr',
    '-cq',
    '19',
    '-b:v',
    '0',
    '-profile:v',
    'high',
    '-movflags',
    '+faststart',
    FINAL,
  ];
  return new Promise((resolve, reject) => {
    const ff = spawn('ffmpeg', args, { stdio: 'inherit' });
    ff.on('close', (code) => (code === 0 ? resolve() : reject(new Error(`ffmpeg ${code}`))));
  });
}

// --------------------------------------------------------------------------- страницы вне сервиса

const FONT =
  "<link href='https://fonts.googleapis.com/css2?family=Montserrat:wght@500;600;700;800&display=swap' rel='stylesheet'>";

const INTRO = `<!doctype html><html lang="ru"><head><meta charset="utf-8">${FONT}<style>
html,body{margin:0;height:100%;background:#310F53;color:#fff;font-family:Montserrat,sans-serif;overflow:hidden}
.card{position:absolute;inset:0;display:flex;flex-direction:column;justify-content:center;padding:0 160px;
 background:radial-gradient(1200px 700px at 80% 20%,rgba(255,0,83,.35),transparent),#310F53}
h1{margin:0;font-size:150px;font-weight:800;letter-spacing:-.04em;line-height:1}
p{margin:26px 0 0;font-size:40px;font-weight:600;max-width:1300px;line-height:1.3}
small{display:block;margin-top:40px;font-size:26px;font-weight:500;color:rgba(255,255,255,.75)}
.end{display:none}body.final .start{display:none}body.final .end{display:flex}
</style></head><body><div class="card start"><h1>green</h1>
<p>Озеленение улицы по нормам и подземным сетям: DXF на входе, план с объяснениями на выходе</p>
<small>Демо сервиса · команда MISIS MOJARUNG · ЛЦТ 2026</small></div>
<div class="card end"><h1>green</h1><p>Весь код, документация и Docker-образ:</p>
<small style="font-size:40px;color:#fff">github.com/Mojarung/LCT_2026</small></div>
<script>if(location.hash==='#end')document.body.classList.add('final')</script></body></html>`;

const VERIFY = existsSync(join(out, 'verify.json'))
  ? readFileSync(join(out, 'verify.json'), 'utf8')
  : '{\n  "ok": true,\n  "source_entities": 12694,\n  "unchanged": 12694,\n  "changed": [],\n  "missing": [],\n  "added_outside_result_layers": []\n}';

const CAD = `<!doctype html><html lang="ru"><head><meta charset="utf-8">${FONT}<style>
html,body{margin:0;height:100%;background:#1C1D22;overflow:hidden}
img{position:absolute;left:160px;top:40px;width:1600px;height:1000px;border-radius:10px;
 box-shadow:0 20px 60px rgba(0,0,0,.5);transition:opacity .6s}
pre{position:absolute;right:120px;bottom:90px;margin:0;padding:28px 34px;border-radius:14px;
 background:#0E0F12;color:#E8E6EF;font:600 25px/1.45 'JetBrains Mono',Consolas,monospace;
 box-shadow:0 20px 60px rgba(0,0,0,.6);opacity:0;transform:translateY(20px);transition:all .6s}
pre i{color:#FF6A95;font-style:normal}
body.verify pre{opacity:1;transform:none}body.verify img{opacity:.35}
</style></head><body><img src="result.png" alt="">
<pre><i>$</i> green verify улица.dxf result.dxf
${VERIFY.replace(/</g, '&lt;')}</pre></body></html>`;

if (process.argv.includes('--edit')) {
  await edit();
} else {
  await record();
  await edit();
}
console.log('готово', FINAL);
