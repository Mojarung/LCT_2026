// Презентация в PDF для сдачи (ТЗ, разд. 4: pptx или pdf): по кадру на слайд, последний кадр
// анимации слайда, 1920 x 1080.
// Запуск (Chromium и playwright-core - из tools/docs):
//   node tools/presentation/build.mjs && node tools/presentation/export-pdf.mjs
//   -> docs/presentation.pdf
import { writeFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, '..', '..');
const require = createRequire(join(root, 'tools', 'docs', 'package.json'));
const { chromium } = require('playwright-core');

const html = pathToFileURL(join(root, 'docs', 'presentation.html')).href;
const out = join(root, 'docs', 'presentation.pdf');
const W = 1920;
const H = 1080;
// Кадр слайда - незадолго до конца: анимация доиграна, подписи ещё на месте (они гаснут
// за 0,9 с до конца слайда), переход к следующему не начался.
const TAIL_S = 1.2;

// Свой Chromium Playwright, а если его версии нет - установленный Chrome.
const app = await chromium.launch().catch(() => chromium.launch({ channel: 'chrome' }));
const page = await app.newPage({ viewport: { width: W, height: H } });
await page.goto(html);
await page.waitForFunction(() => window.FILM && typeof window.FILM.shot === 'function');
// Кадр рисует отладочная функция плеера FILM.shot(слайд, время слайда, общее время) - тот же
// рисунок, что на показе, без ожидания прогрева.
const frames = await page.evaluate((tail) => {
  const film = window.FILM;
  return film.SLIDES.map((slide, i) =>
    film.shot(i, Math.max(0, slide.dur - tail), 60).replace(/^data:image\/png;base64,/, ''),
  );
}, TAIL_S);
const sheet = await app.newPage();
await sheet.setContent(`<!doctype html><html><head><style>
@page { size: ${W}px ${H}px; margin: 0 }
html, body { margin: 0 }
img { display: block; width: ${W}px; height: ${H}px; page-break-after: always }
img:last-child { page-break-after: auto }
</style></head><body>${frames
  .map((b64) => `<img src="data:image/png;base64,${b64}">`)
  .join('')}</body></html>`);
const pdf = await sheet.pdf({ width: `${W}px`, height: `${H}px`, printBackground: true });
await writeFile(out, pdf);
await app.close();
console.log(`${out}: ${frames.length} слайдов, ${Math.round(pdf.length / 1024)} КБ`);
