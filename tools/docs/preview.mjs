// Страницы PDF в PNG для просмотра глазами: node preview.mjs <in.pdf> <outdir> 1,2,3
import { readFile, writeFile } from 'node:fs/promises';
import { chromium } from 'playwright-core';
const [input, outdir, list] = process.argv.slice(2);
const pages = list.split(',').map(Number);
const app = await chromium.launch({ args: ['--allow-file-access-from-files'] });
const page = await app.newPage({ viewport: { width: 1240, height: 1754 } });
const pdfjs = new URL('./node_modules/pdfjs-dist/legacy/build/pdf.mjs', 'file:///C:/proga/active/LCT_2026/tools/docs/').href;
const data = (await readFile(input)).toString('base64');
await page.goto(new URL('./preview.html', import.meta.url).href);
for (const n of pages) {
  const png = await page.evaluate(async ({ pdfjs, data, n }) => {
    const lib = await import(pdfjs);
    lib.GlobalWorkerOptions.workerSrc = pdfjs.replace('pdf.mjs', 'pdf.worker.mjs');
    const doc = await lib.getDocument({ data: Uint8Array.from(atob(data), c => c.charCodeAt(0)) }).promise;
    const p = await doc.getPage(n);
    const vp = p.getViewport({ scale: 1.5 });
    const c = document.getElementById('c'); c.width = vp.width; c.height = vp.height;
    await p.render({ canvasContext: c.getContext('2d'), viewport: vp }).promise;
    return c.toDataURL('image/png').split(',')[1];
  }, { pdfjs, data, n });
  await writeFile(`${outdir}/p${String(n).padStart(2, '0')}.png`, Buffer.from(png, 'base64'));
}
await app.close();
