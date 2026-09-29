// Свободные слайды презентации в стиле шаблона ЛЦТ 2026: HTML 1920 x 1080 -> PDF и PNG.
// Запуск: node tools/presentation/pitch/build.mjs  (снимки - shots.mjs, фоны - bg/ из шаблона)
// Выход: out/presentation/pitch/deck.html, free.pdf, slides/NN.png.
import { mkdirSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

import { chromium } from '../../../frontend/node_modules/@playwright/test/index.mjs';
import { AUDIT, CUSTOMER, DEMO, STREETS, facts } from './data.mjs';

const here = dirname(fileURLToPath(import.meta.url));
const out = join(here, '..', '..', '..', 'out', 'presentation', 'pitch');
mkdirSync(join(out, 'slides'), { recursive: true });

const C = {
  pink: '#FF0053',
  rose: '#FC3777',
  blush: '#FFD6E4',
  lav: '#8A83D1',
  plum: '#520978',
  night: '#310F53',
  ink: '#1C1D22',
  mute: '#5E5670',
};

const num = (v) => String(v).replace('.', ',');

// --------------------------------------------------------------------------- графики SVG

function hbars(rows, { width, row = 46, color = C.pink, labelW = 300, unit = '' }) {
  const max = Math.max(...rows.map((r) => r[1]));
  const barW = width - labelW - 90;
  const h = rows.length * row;
  const bars = rows
    .map(([label, value], i) => {
      const y = i * row;
      const w = Math.max(4, (value / max) * barW);
      return `<text x="${labelW - 16}" y="${y + row / 2 + 8}" text-anchor="end" class="lab">${label}</text>
<rect x="${labelW}" y="${y + 8}" width="${w}" height="${row - 16}" rx="4" fill="${color}"/>
<text x="${labelW + w + 12}" y="${y + row / 2 + 8}" class="val">${num(value)}${unit}</text>`;
    })
    .join('');
  return `<svg width="${width}" height="${h}" viewBox="0 0 ${width} ${h}">${bars}</svg>`;
}

function beforeAfter(rows, { width, row = 64, labelW = 290 }) {
  const barW = width - labelW - 100;
  const max = 72;
  const h = rows.length * row;
  const g = rows
    .map(([label, , a, b], i) => {
      const y = i * row;
      const wa = (a / max) * barW;
      const wb = (b / max) * barW;
      return `<text x="${labelW - 16}" y="${y + 34}" text-anchor="end" class="lab">${label}</text>
<rect x="${labelW}" y="${y + 8}" width="${wa}" height="20" rx="3" fill="${C.lav}"/>
<rect x="${labelW}" y="${y + 32}" width="${wb}" height="20" rx="3" fill="${C.pink}"/>
<text x="${labelW + wb + 12}" y="${y + 48}" class="val">${num(a)} → ${num(b)}%</text>`;
    })
    .join('');
  return `<svg width="${width}" height="${h}" viewBox="0 0 ${width} ${h}">${g}</svg>`;
}

function timeColumns(rows, { width, height }) {
  const sorted = [...rows].sort((a, b) => a[1] - b[1]);
  const top = 70;
  const plotH = height - top - 190;
  const max = CUSTOMER.frameMinutes;
  // Слева запас под повёрнутые подписи: иначе первое название уходит за край.
  const pad = 110;
  const step = (width - pad) / sorted.length;
  const y = (m) => top + plotH - (m / max) * plotH;
  const cols = sorted
    .map(([name, m], i) => {
      const x = pad + i * step + step * 0.18;
      const w = step * 0.64;
      return `<rect x="${x}" y="${y(m)}" width="${w}" height="${top + plotH - y(m)}" rx="4" fill="${C.pink}"/>
<text x="${x + w / 2}" y="${y(m) - 10}" text-anchor="middle" class="val sm">${num(m)}</text>
<text transform="translate(${x + w / 2},${top + plotH + 18}) rotate(-45)" text-anchor="end" class="lab sm">${name}</text>`;
    })
    .join('');
  const line = (m, label) =>
    `<line x1="0" x2="${width}" y1="${y(m)}" y2="${y(m)}" stroke="${C.plum}" stroke-width="2" stroke-dasharray="10 8"/>
<text x="0" y="${y(m) - 12}" class="ref">${label}</text>`;
  return `<svg width="${width}" height="${height}" viewBox="0 0 ${width} ${height}">${line(
    CUSTOMER.frameMinutes,
    'рамка заказчика: генерация до 60 мин',
  )}${line(CUSTOMER.pickMinutes, 'подбор мест до 30 мин')}${cols}</svg>`;
}

function donut(part, total, { size = 360, stroke = 54 }) {
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const share = part / total;
  return `<svg width="${size}" height="${size}" viewBox="0 0 ${size} ${size}">
<circle cx="${size / 2}" cy="${size / 2}" r="${r}" fill="none" stroke="${C.blush}" stroke-width="${stroke}"/>
<circle cx="${size / 2}" cy="${size / 2}" r="${r}" fill="none" stroke="${C.pink}" stroke-width="${stroke}"
 stroke-dasharray="${c * share} ${c}" transform="rotate(-90 ${size / 2} ${size / 2})"/>
<text x="50%" y="53%" text-anchor="middle" class="donut-n">${Math.round(share * 100)}%</text></svg>`;
}

// --------------------------------------------------------------------------- слайды

const img = (name, cls = '', style = '') =>
  `<img class="screen ${cls}" src="shots/${name}" style="${style}" alt="">`;

const f = facts;
const topCurb = [...STREETS].sort((a, b) => b[3] - b[2] - (a[3] - a[2])).slice(0, 7);

const slides = [
  // 1. Задача
  {
    bg: 'light',
    html: `
<h1 class="title">Под газоном идут кабели и трубы</h1>
<div class="crop" style="left:96px;top:300px;width:1000px;height:640px">
  ${img('plan-street-dark.png', 'fill', 'object-position:52% 50%;transform:scale(1.55);transform-origin:52% 48%')}
</div>
<div class="col" style="left:1160px;top:300px;width:660px">
  <p class="lead">Дерево нельзя посадить ближе 2 м к силовому кабелю, 1,5 м к газопроводу, 5 м к стене дома. Проектировщик сверяет каждое место с сетями на чертеже вручную.</p>
  <p class="body">Разбор сетей на геоподоснове заказчик назвал самым трудоёмким этапом проекта. На чертеже Кустанайской улицы 59 562 места вдоль бортов, нормы проходит 3 571.</p>
  <p class="cap">Слева: подземные сети Кустанайской улицы в рабочем месте сервиса.</p>
</div>`,
  },
  // 2. Решение
  {
    bg: 'dark',
    html: `
<h1 class="title">Чертёж на входе, план с объяснениями на выходе</h1>
<div class="flow">
  <figure><div class="crop" style="width:520px;height:400px">${img('plan-street-dark.png', 'fill', 'object-position:55% 50%;transform:scale(1.8);transform-origin:55% 50%')}</div>
    <figcaption><b>DXF или DWG улицы</b>подоснова Мосгеотреста и сети</figcaption></figure>
  <span class="arrow">→</span>
  <figure><div class="crop" style="width:520px;height:400px">${img('plan-street-light.png', 'fill', 'object-position:55% 50%;transform:scale(1.8);transform-origin:55% 50%')}</div>
    <figcaption><b>План посадок</b>деревья, кустарники и газоны на слоях GREEN_*</figcaption></figure>
  <span class="arrow">→</span>
  <figure><div class="crop" style="width:520px;height:400px">${img('plan-selected.png', 'fill', 'object-position:100% 20%')}</div>
    <figcaption><b>Объяснение каждой посадки</b>замер, норма, акт и пункт</figcaption></figure>
</div>
<p class="foot">Исходные слои чертежа не меняются: сверено ${f.entities} объектов, изменено ${f.entities_changed}.</p>`,
  },
  // 3. Как работает
  {
    bg: 'light',
    html: `
<h1 class="title">Семь шагов от DXF до DXF</h1>
<ol class="steps">
  <li><b>Чтение без потерь</b><span>каждый примитив учтён, чертёж перерисовывается и сверяется с исходником</span></li>
  <li><b>Классы слоёв и знаков</b><span>сети, борта, здания, существующие деревья; 179 условных знаков съёмки</span></li>
  <li><b>Карта покрытий</b><span>газон, тротуар и проезд: где под ямой грунт</span></li>
  <li><b>Места посадки</b><span>аллея вдоль борта, группы на газоне, ряды и изгороди кустарника</span></li>
  <li><b>Вид под место</b><span>${f.species} видов, подбор задачей MILP по условиям места и квотам</span></li>
  <li><b>Независимая проверка</b><span>${f.rules_total} правил заново по готовому плану, в выдаче ${f.violations} нарушений</span></li>
  <li><b>Запись и объяснения</b><span>слои GREEN_*, блоки видов, ведомость, CSV и отчёт с пунктами актов</span></li>
</ol>
<p class="foot dark-ink">Нормы лежат в YAML: при новой редакции акта правится файл, а не код. СП 42.13330 в редакциях 2016 и 2026 переключается параметром.</p>`,
  },
  // 4. Объяснимость
  {
    bg: 'light',
    html: `
<h1 class="title">У каждой посадки есть пункт нормы</h1>
<div class="crop framed" style="left:96px;top:280px;width:1180px;height:680px">${img('plan-selected.png', 'fill', 'object-position:78% 30%')}</div>
<div class="col" style="left:1340px;top:300px;width:490px">
  <p class="lead">Выноска на карте показывает замер: «теплосеть 13,23 ≥ 4,00». В карточке - правило, акт, пункт и дословная цитата.</p>
  <p class="body">Свод: ${f.rules_total} правил из ${f.acts} актов, основание ${f.rules_verified} сверено по тексту. Объяснение собирается из трассы проверок без языковой модели, поэтому одинаковый вход даёт одинаковый текст.</p>
</div>`,
  },
  // 5. Нормоконтроль
  {
    bg: 'light',
    html: `
<h1 class="title">Сервис проверяет и чужие планы</h1>
<div class="col" style="left:96px;top:290px;width:520px">
  ${donut(391, 554, { size: 340 })}
  <p class="body" style="margin-top:28px">В принятом плане улицы Берзарина 391 из 554 посадок нарушают отступы. Нормоконтроль занял 162 с.</p>
  <p class="body">В плане сервиса для той же улицы нарушений ${f.violations}.</p>
</div>
<div class="col" style="left:760px;top:290px;width:1060px">
  <p class="chart-title">785 нарушений по видам объектов</p>
  ${hbars(AUDIT, { width: 1060, row: 64, labelW: 290 })}
</div>`,
  },
  // 6. Скорость
  {
    bg: 'light',
    html: `
<h1 class="title">Каждая улица пилота - за один прогон</h1>
<div class="col" style="left:96px;top:250px;width:1728px">
  <p class="chart-title">Минуты прогона по 18 улицам, медиана ${f.minutes_median}</p>
  ${timeColumns(STREETS, { width: 1728, height: 660 })}
</div>
<p class="foot dark-ink">Демонстрационный фрагмент улицы Берзарина: ${DEMO.placements} посадок за ${DEMO.seconds} с. Полный цикл на стенде: чтение, план, проверка, запись DXF.</p>`,
  },
  // 7. Эффект
  {
    bg: 'dark',
    html: `
<h1 class="title">План добавляет улицам тень и защиту от пыли</h1>
<div class="col" style="left:96px;top:280px;width:1050px">
  <p class="chart-title light">Борта под кронами и кустарником, %: <span style="color:${C.lav}">было</span> и <span style="color:${C.rose}">с планом сервиса</span></p>
  ${beforeAfter(topCurb, { width: 1050, row: 86, labelW: 300 })}
</div>
<dl class="facts" style="left:1250px;top:300px;width:600px">
  <dt>${f.effect_curb}</dt><dd>на 18 улицах пилота, прирост ${f.effect_curb_m}</dd>
  <dt>${f.effect_canopy_m2}</dt><dd>площади взрослых крон, доля участков ${f.effect_canopy}</dd>
  <dt>${f.effect_tiers}</dt><dd>деревьев с кустарником под кроной</dd>
</dl>`,
  },
  // 8. Правка
  {
    bg: 'light',
    html: `
<h1 class="title">План можно поправить в браузере</h1>
<div class="crop framed" style="left:96px;top:270px;width:1240px;height:700px">${img('plan-demo.png', 'fill', 'object-position:50% 50%')}</div>
<ol class="mini" style="left:1400px;top:300px;width:430px">
  <li>Тянем посадку мышью или клавишами.</li>
  <li>Сервис на лету проверяет новое место теми же ${f.rules_total} правилами и рисует выноски до сетей.</li>
  <li>Кнопка пересборки переписывает DXF и объяснения.</li>
</ol>`,
  },
  // 9. 3D и кадры
  {
    bg: 'dark',
    html: `
<h1 class="title">Участок в 3D по тем же координатам</h1>
<div class="crop framed" style="left:96px;top:270px;width:1060px;height:600px">${img('scene3d.png', 'fill', 'object-position:50% 60%')}</div>
<div class="crop framed" style="left:1200px;top:270px;width:624px;height:600px">${img('gallery-plant.png', 'fill', 'object-position:50% 30%')}</div>
<p class="foot">Здания по этажности из подписей чертежа, кроны по виду и возрасту, солнце по часу над Москвой. Кадры посадки и улицы подбираются автоматически: объект виден, дома и соседние кроны не заслоняют.</p>`,
  },
  // 10. Фото
  {
    bg: 'light',
    html: `
<h1 class="title">Фото, на котором деревья стоят по плану</h1>
<div class="pairs">
  <div class="pair"><div class="crop framed">${img('photo-false-src.png', 'fill')}</div><span class="arrow ink">→</span><div class="crop framed">${img('photo-false.jpg', 'fill')}</div></div>
  <div class="pair"><div class="crop framed">${img('tour-src.png', 'fill')}</div><span class="arrow ink">→</span><div class="crop framed">${img('tour-photo.png', 'fill')}</div></div>
</div>
<p class="foot dark-ink">Кадр 3D-вида перерисовывает модель Qwen-Image-2.1 локально: 6 ГБ видеопамяти, около 80 с на кадр. Расстановка посадок сохраняется; фон и лишние деревья модель дорисует только по галочке.</p>`,
  },
  // 11. Что получает город
  {
    bg: 'light',
    html: `
<h1 class="title">Что получает город</h1>
<table class="compare" style="left:96px;top:270px;width:1728px">
  <thead><tr><th></th><th>Сейчас</th><th>С сервисом green</th></tr></thead>
  <tbody>
    <tr><td>Проверка отступов</td><td>вручную по чертежу сетей</td><td>${f.rules_total} правил на каждое место, ${f.violations} нарушений на 18 улицах</td></tr>
    <tr><td>Время на улицу</td><td>рамка заказчика: до 1 ч на генерацию</td><td>медиана ${f.minutes_median} мин, фрагмент ${DEMO.seconds} с</td></tr>
    <tr><td>Обоснование для согласования</td><td>пояснительная записка</td><td>у каждой посадки замер, акт, пункт и цитата</td></tr>
    <tr><td>Проверка готового проекта</td><td>экспертиза вручную</td><td>нормоконтроль за 162 с, нарушение с недобором в метрах</td></tr>
    <tr><td>Новая редакция норм</td><td>сверка по новой редакции вручную</td><td>правка YAML, СП 42.13330 2016 и 2026</td></tr>
  </tbody>
</table>
<p class="foot dark-ink">Озеленение улицы районного значения стоит ${CUSTOMER.costPerHa} на гектар (ориентир заказчика). Ошибку в отступе дешевле найти на чертеже, чем после посадки.</p>`,
  },
  // 12. Внедрение
  {
    bg: 'dark',
    html: `
<h1 class="title">Разворачивается одной командой</h1>
<div class="arch" style="left:96px;top:280px;width:960px">
  <div class="stack">
    <div class="box">CLI<small>green run, audit, verify</small></div>
    <div class="box">HTTP API<small>OpenAPI 3.1, Swagger без сети</small></div>
    <div class="box">Веб-интерфейс<small>React, правка плана, 3D</small></div>
  </div>
  <span class="arrow">→</span>
  <div class="box core">Одно ядро<small>нормы как данные, без фреймворков</small></div>
</div>
<pre class="cmd" style="left:96px;top:720px">docker compose up --build</pre>
<p class="foot" style="width:900px">Образ Ubuntu 26.04 без GPU и внешних сервисов, как МосТех.ОС. Манифесты Kubernetes проверены kubeconform.</p>
<div class="crop framed" style="left:1130px;top:280px;width:694px;height:560px">${img('swagger.png', 'fill', 'object-position:22% 4%;transform:scale(1.25);transform-origin:22% 4%')}</div>`,
  },
  // 13. Финал
  {
    bg: 'city',
    html: `
<div class="final">
  <p class="brand">green</p>
  <p class="lead">Озеленение улиц по нормам и подземным сетям</p>
  <p class="body">Команда MISIS MOJARUNG<br>github.com/Mojarung/LCT_2026</p>
</div>`,
  },
];

// --------------------------------------------------------------------------- страница

const css = `
@page { size: 1920px 1080px; margin: 0 }
* { box-sizing: border-box }
html, body { margin: 0; background: #222 }
body { font-family: 'Montserrat', sans-serif; font-variant-numeric: tabular-nums lining-nums }
.slide { width: 1920px; height: 1080px; position: relative; overflow: hidden; background-size: cover;
  break-after: page; }
.slide.light { background-image: url(bg/light.png); color: ${C.ink} }
.slide.dark { background-image: url(bg/dark.png); color: #fff }
.slide.city { background-image: url(bg/city.png); color: #fff }
.title { position: absolute; left: 96px; top: 120px; margin: 0; max-width: 1400px; font-size: 64px;
  font-weight: 800; line-height: 1.06; letter-spacing: -0.02em; text-wrap: balance }
.light .title { color: ${C.night} }
.col, .crop, .facts, .mini, .compare, .arch, .cmd { position: absolute }
.crop { overflow: hidden; border-radius: 18px }
.crop .fill { width: 100%; height: 100%; object-fit: cover; display: block }
.framed { box-shadow: 0 24px 60px rgba(49, 15, 83, 0.28) }
.dark .framed { box-shadow: 0 24px 60px rgba(0, 0, 0, 0.45) }
.lead { margin: 0 0 28px; font-size: 32px; font-weight: 600; line-height: 1.3 }
.body { margin: 0 0 20px; font-size: 26px; font-weight: 500; line-height: 1.45 }
.light .body { color: #3c3548 }
.cap { margin: 36px 0 0; font-size: 20px; color: ${C.mute} }
.foot { position: absolute; left: 96px; bottom: 70px; margin: 0; max-width: 1600px; font-size: 24px;
  font-weight: 500; line-height: 1.45; color: rgba(255, 255, 255, 0.86) }
.foot.dark-ink { color: #3c3548 }
.chart-title { margin: 0 0 22px; font-size: 26px; font-weight: 700; color: ${C.night} }
.chart-title.light { color: #fff }
svg .lab { font: 500 22px Montserrat; fill: #3c3548 }
.dark svg .lab { fill: rgba(255, 255, 255, 0.88) }
svg .val { font: 700 22px Montserrat; fill: ${C.night} }
.dark svg .val { fill: #fff }
svg .sm { font-size: 18px }
svg .ref { font: 600 20px Montserrat; fill: ${C.plum} }
svg .donut-n { font: 800 84px Montserrat; fill: ${C.pink} }
svg .donut-l { font: 600 22px Montserrat; fill: #3c3548 }
.flow { position: absolute; left: 96px; top: 300px; display: flex; align-items: flex-start; gap: 28px }
.flow figure { margin: 0 }
.flow .crop { position: relative }
.flow figcaption { margin-top: 22px; font-size: 22px; line-height: 1.4; color: rgba(255,255,255,.8); max-width: 520px }
.flow figcaption b { display: block; font-size: 28px; font-weight: 700; color: #fff; margin-bottom: 4px }
.arrow { font-size: 56px; font-weight: 300; color: ${C.rose}; align-self: center; margin-top: -120px }
.arrow.ink { margin: 0 }
.steps { position: absolute; left: 96px; top: 330px; width: 1728px; margin: 0; padding: 0; list-style: none;
  display: grid; grid-template-columns: repeat(7, 1fr); gap: 20px; counter-reset: s }
.steps li { counter-increment: s; padding-top: 86px; position: relative; border-top: 4px solid ${C.pink} }
.steps li::before { content: counter(s); position: absolute; top: 18px; left: 0; font-size: 48px;
  font-weight: 800; color: ${C.pink} }
.steps b { display: block; font-size: 30px; line-height: 1.2; color: ${C.night}; margin-bottom: 14px }
.steps span { display: block; font-size: 23px; line-height: 1.45; color: #3c3548 }
.facts { margin: 0 }
.facts dt { font-size: 44px; font-weight: 800; color: ${C.rose}; line-height: 1.1 }
.facts dd { margin: 6px 0 40px; font-size: 24px; line-height: 1.4; color: rgba(255,255,255,.86) }
.mini { margin: 0; padding: 0; list-style: none; counter-reset: m }
.mini li { counter-increment: m; position: relative; padding-left: 64px; margin-bottom: 44px;
  font-size: 28px; font-weight: 500; line-height: 1.4 }
.mini li::before { content: counter(m); position: absolute; left: 0; top: -4px; width: 44px; height: 44px;
  border-radius: 50%; background: ${C.pink}; color: #fff; font-size: 24px; font-weight: 800;
  display: grid; place-items: center }
.pairs { position: absolute; left: 96px; top: 300px; display: grid; gap: 34px }
.pair { display: flex; align-items: center; gap: 26px }
.pair .crop { position: relative; width: 740px; height: 290px }
.compare { border-collapse: collapse; font-size: 26px }
.compare th { text-align: left; font-size: 24px; font-weight: 700; color: ${C.plum}; padding: 0 24px 18px 0 }
.compare td { padding: 22px 24px 22px 0; border-top: 2px solid ${C.blush}; line-height: 1.35; vertical-align: top }
.compare td:first-child { font-weight: 700; color: ${C.night}; width: 400px }
.compare td:nth-child(2) { color: ${C.mute}; width: 520px }
.compare td:nth-child(3) { font-weight: 600; color: ${C.ink} }
.compare td:nth-child(3)::before { content: ''; display: inline-block; width: 12px; height: 12px;
  border-radius: 50%; background: ${C.pink}; margin-right: 14px; vertical-align: 3px }
.arch { display: flex; align-items: center; gap: 34px }
.arch .stack { display: grid; gap: 18px }
.arch .box { width: 400px; padding: 22px 26px; border-radius: 16px; background: rgba(255,255,255,.1);
  border: 1.5px solid rgba(255,255,255,.28); font-size: 28px; font-weight: 700 }
.arch .box small { display: block; margin-top: 6px; font-size: 20px; font-weight: 500; color: rgba(255,255,255,.75) }
.arch .core { background: ${C.pink}; border-color: ${C.pink}; width: 420px }
.arch .core small { color: rgba(255,255,255,.9) }
.arch .arrow { margin: 0 }
.cmd { margin: 0; padding: 20px 30px; border-radius: 14px; background: rgba(0,0,0,.35); font: 600 30px/1 'JetBrains Mono', monospace; color: #fff }
.final { position: absolute; left: 120px; top: 360px; width: 1000px }
.final .brand { margin: 0; font-size: 190px; font-weight: 800; letter-spacing: -0.04em; line-height: 1 }
.final .lead { margin: 18px 0 40px; font-size: 40px; font-weight: 600 }
.final .body { color: rgba(255,255,255,.86); font-size: 28px }
.num { position: absolute; right: 64px; bottom: 34px; font-size: 18px; font-weight: 600; opacity: .6 }
`;

const START = 6; // первые пять страниц - обязательные слайды шаблона
const html = `<!doctype html><html lang="ru"><head><meta charset="utf-8">
<title>green - презентация</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Montserrat:wght@300;500;600;700;800&family=JetBrains+Mono:wght@600&display=swap" rel="stylesheet">
<style>${css}</style></head><body>
${slides.map((s, i) => `<section class="slide ${s.bg}">${s.html}<span class="num">${START + i}</span></section>`).join('\n')}
</body></html>`;

writeFileSync(join(out, 'deck.html'), html);
console.log('deck.html', slides.length, 'слайдов');

const browser = await chromium.launch({ channel: 'chrome' });
const page = await browser.newPage({ viewport: { width: 1920, height: 1080 } });
await page.goto(`file:///${join(out, 'deck.html').replace(/\\/g, '/')}`);
await page.evaluate(() => document.fonts.ready);
await page.waitForTimeout(800);
await page.pdf({
  path: join(out, 'free.pdf'),
  width: '1920px',
  height: '1080px',
  printBackground: true,
});
const sections = await page.$$('section.slide');
for (const [i, el] of sections.entries()) {
  await el.screenshot({
    path: join(out, 'slides', `${String(START + i).padStart(2, '0')}.png`),
  });
}
await browser.close();
console.log('free.pdf и slides/*.png готовы');
