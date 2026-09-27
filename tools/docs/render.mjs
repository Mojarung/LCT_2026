// Рендер для документации: BPMN 2.0 в SVG, HTML в PDF (безголовый Chromium).
//
//   node render.mjs diagrams <папка>   - *.bpmn: раскладка (bpmn-auto-layout) и SVG через bpmn-js;
//                                         раскладка пишется обратно в *.bpmn для Camunda Modeler
//   node render.mjs pdf <вход.html> <выход.pdf> [страницы.json]
//                                       - поля страницы из CSS (@page): титул без колонтитулов;
//                                         страницы.json - заголовки закладок PDF и их страницы,
//                                         по ним сборщик проставляет номера в оглавлении
import { readdir, readFile, writeFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

import { layoutProcess } from 'bpmn-auto-layout';
import { chromium } from 'playwright-core';
import { getDocument } from 'pdfjs-dist/legacy/build/pdf.mjs';

const require = createRequire(import.meta.url);
const BPMN_VIEWER = require.resolve('bpmn-js/dist/bpmn-navigated-viewer.production.min.js');
const BPMN_CSS = require.resolve('bpmn-js/dist/assets/bpmn-js.css');
const BPMN_FONT_CSS = require.resolve('bpmn-js/dist/assets/bpmn-font/css/bpmn.css');

async function browser() {
  return chromium.launch();
}

async function diagrams(folder) {
  const names = await readdir(folder);
  const app = await browser();
  const page = await app.newPage({ viewport: { width: 1800, height: 1200 } });
  for (const name of names.filter((n) => n.endsWith('.bpmn'))) {
    const file = path.join(folder, name);
    const source = await readFile(file, 'utf8');
    const laid = source.includes('bpmndi:BPMNDiagram') ? source : await layoutProcess(source);
    if (laid !== source) await writeFile(file, laid);
    await page.setContent('<div id="c" style="width:1700px;height:1100px"></div>');
    await page.addStyleTag({ path: BPMN_CSS });
    await page.addStyleTag({ path: BPMN_FONT_CSS });
    await page.addScriptTag({ path: BPMN_VIEWER });
    const svg = await page.evaluate(async (xml) => {
      const viewer = new window.BpmnJS({
        container: '#c',
        textRenderer: {
          defaultStyle: { fontFamily: 'Arial, sans-serif', fontSize: 17, lineHeight: 1.15 },
          externalStyle: { fontSize: 16, lineHeight: 1.15 },
        },
      });
      await viewer.importXML(xml);
      const { svg } = await viewer.saveSVG();
      return svg;
    }, laid);
    await writeFile(file.replace(/\.bpmn$/, '.svg'), svg);
    console.log('bpmn', name);
  }
  await app.close();
}

async function pdf(input, output, pagesFile) {
  const app = await browser();
  const page = await app.newPage();
  await page.goto(pathToFileURL(path.resolve(input)).href, { waitUntil: 'networkidle' });
  await page.evaluate(() => document.fonts.ready);
  await page.pdf({
    path: output,
    preferCSSPageSize: true,
    printBackground: true,
    outline: true,
    tagged: true,
  });
  await app.close();
  console.log('pdf', output);
  if (pagesFile) await writeFile(pagesFile, JSON.stringify(await outlinePages(output), null, 1));
}

// Закладки PDF (Chromium строит их по заголовкам) и номер страницы каждой, с единицы.
async function outlinePages(file) {
  const doc = await getDocument({ data: new Uint8Array(await readFile(file)) }).promise;
  const found = [];
  async function walk(items) {
    for (const item of items ?? []) {
      const dest = typeof item.dest === 'string' ? await doc.getDestination(item.dest) : item.dest;
      if (dest) found.push({ title: item.title, page: (await doc.getPageIndex(dest[0])) + 1 });
      await walk(item.items);
    }
  }
  await walk(await doc.getOutline());
  return { pages: doc.numPages, headings: found };
}

const [command, ...args] = process.argv.slice(2);
if (command === 'diagrams') await diagrams(args[0]);
else if (command === 'pdf') await pdf(args[0], args[1], args[2]);
else {
  console.error('usage: node render.mjs diagrams <folder> | pdf <in.html> <out.pdf> [pages.json]');
  process.exit(2);
}
