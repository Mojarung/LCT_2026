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

// Третий элемент строки - сводная полоса (прочее): другой цвет, чтобы не читалась как ошибка сортировки.
function hbars(rows, { width, row = 46, color = C.pink, labelW = 300, unit = '' }) {
  const max = Math.max(...rows.map((r) => r[1]));
  const barW = width - labelW - 90;
  const h = rows.length * row;
  const bars = rows
    .map(([label, value, rest], i) => {
      const y = i * row;
      const w = Math.max(4, (value / max) * barW);
      return `<text x="${labelW - 16}" y="${y + row / 2 + 8}" text-anchor="end" class="lab">${label}</text>
<rect x="${labelW}" y="${y + 8}" width="${w}" height="${row - 16}" rx="4" fill="${rest ? C.lav : color}"/>
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
  const plotH = height - top - 230;
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

function donut(part, total, { size = 360, stroke = 54, label = '' }) {
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const share = part / total;
  return `<svg width="${size}" height="${size}" viewBox="0 0 ${size} ${size}">
<circle cx="${size / 2}" cy="${size / 2}" r="${r}" fill="none" stroke="${C.blush}" stroke-width="${stroke}"/>
<circle cx="${size / 2}" cy="${size / 2}" r="${r}" fill="none" stroke="${C.pink}" stroke-width="${stroke}"
 stroke-dasharray="${c * share} ${c}" transform="rotate(-90 ${size / 2} ${size / 2})"/>
<text x="50%" y="${label ? '50%' : '53%'}" text-anchor="middle" class="donut-n">${Math.round(share * 100)}%</text>${
    label
      ? `<text x="50%" y="62%" text-anchor="middle" class="donut-l">${label
          .split('\n')
          .map((line, i) => `<tspan x="50%" dy="${i ? 26 : 0}">${line}</tspan>`)
          .join('')}</text>`
      : ''
  }</svg>`;
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
  ${img('utilities.png', 'fill', 'object-position:50% 0;transform:scale(1.65);transform-origin:52% 18%')}
</div>
<div class="col" style="left:1160px;top:300px;width:660px">
  <p class="lead">Дерево нельзя посадить ближе 2 м к силовому кабелю, 1,5 м к газопроводу, 5 м к стене дома (СП 42.13330.2016, табл. 9.1). Проектировщик сверяет каждое место с сетями на чертеже вручную.</p>
  <p class="body">Разбор сетей на геоподоснове заказчик назвал самым трудоёмким этапом проекта. На чертеже Кустанайской улицы 59&nbsp;562 точки-кандидата вдоль бортов, нормы проходят 3&nbsp;571.</p>
  <p class="cap">Слева: подземные сети Кустанайской улицы, слои плана скрыты.</p>
</div>`,
  },
  // 2. Решение
  {
    bg: 'dark',
    html: `
<h1 class="title">Чертёж на входе, план с&nbsp;объяснениями на выходе</h1>
<div class="flow">
  <figure><div class="crop" style="width:520px;height:400px">${img('flow-before.png', 'fill', 'object-position:40% 30%;transform:scale(1.5);transform-origin:40% 30%')}</div>
    <figcaption><b>DXF улицы</b>подоснова Мосгеотреста и сети; слои ГИС, перечётная ведомость</figcaption></figure>
  <span class="arrow">→</span>
  <figure><div class="crop" style="width:520px;height:400px">${img('flow-after.png', 'fill', 'object-position:40% 30%;transform:scale(1.5);transform-origin:40% 30%')}</div>
    <figcaption><b>План посадок</b>слои GREEN_*: деревья, кусты, газоны, отказы, зоны допустимости</figcaption></figure>
  <span class="arrow">→</span>
  <figure><div class="crop" style="width:520px;height:400px">${img('explain-card.png', 'fill', 'object-position:50% 0')}</div>
    <figcaption><b>Объяснение каждой посадки</b>замер, норма, акт и пункт</figcaption></figure>
</div>
<p class="foot">Исходные слои чертежа не меняются: на 18 улицах сверено ${f.entities} объектов, изменено ${f.entities_changed}. У каждой посадки в DXF атрибуты вида и нормы.</p>`,
  },
  // 3. Как работает
  {
    bg: 'light',
    html: `
<h1 class="title">Семь шагов от DXF до DXF</h1>
<ol class="steps">
  <li><b>Чтение без потерь</b><span>каждый примитив учтён, чертёж перерисовывается и сверяется с исходником</span></li>
  <li><b>Классы слоёв и знаков</b><span>сети, борта, здания, деревья; 179 знаков съёмки; слои ГИС и охранные зоны ВЛ</span></li>
  <li><b>Карта покрытий</b><span>газон, тротуар и проезд: где под ямой грунт</span></li>
  <li><b>Места посадки</b><span>аллея вдоль борта, группы на газоне, ряды и изгороди кустарника</span></li>
  <li><b>Вид под место</b><span>${f.species} видов, подбор задачей MILP по условиям места и квотам</span></li>
  <li><b>Независимая проверка</b><span>${f.rules_total} правил заново по готовому плану, в выдаче ${f.violations} нарушений</span></li>
  <li><b>Запись и объяснения</b><span>слои GREEN_*, блоки видов, ведомость, CSV и отчёт с пунктами актов</span></li>
</ol>
<p class="foot dark-ink">Алгоритм, а не обучение: норма - порог расстояния, а принятые планы нарушают её в 391 посадке из 554, учиться на них нельзя. Места и виды выбирает задача MILP (HiGHS), каждое решение проверяемо.</p>`,
  },
  // 4. Объяснимость
  {
    bg: 'light',
    html: `
<h1 class="title">У каждой посадки есть пункт нормы</h1>
<div class="crop framed" style="left:96px;top:280px;width:700px;height:680px">${img('explain-map.png', 'fill', 'object-position:30% 45%;transform:scale(1.35);transform-origin:30% 45%')}</div>
<div class="crop framed" style="left:830px;top:280px;width:470px;height:680px">${img('explain-card.png', 'fill', 'object-position:50% 0')}</div>
<div class="col" style="left:1350px;top:290px;width:480px">
  <p class="lead">Выноска на карте показывает замер: «теплосеть 13,23 ≥ 4,00». В карточке - правило, акт, пункт и дословная цитата.</p>
  <p class="body">Отказ объясняется так же: «до газопровода 0,44 м &lt; 1,50 м (R-GAS-TREE-001: СП 42.13330.2016, п. 9.6, табл. 9.1)».</p>
  <p class="body">Свод: ${f.rules_total} правил, ${f.acts} актов. У ${f.rules_by_text} основание сверено по тексту акта, ${f.rules_project} - параметры проекта, ${f.rules_definitions} - определения газонов. Текст собирается из трассы проверок без языковой модели.</p>
</div>`,
  },
  // 5. Нормоконтроль
  {
    bg: 'light',
    html: `
<h1 class="title">Сервис проверяет и чужие планы</h1>
<div class="col" style="left:96px;top:290px;width:520px">
  ${donut(391, 554, { size: 340, label: 'посадок\nс нарушениями' })}
  <p class="body" style="margin-top:28px">В принятом плане улицы Берзарина 391 из 554 посадок нарушают отступы (прогон 18.09.2026, нормоконтроль занял 162 с).</p>
  <p class="body">В плане сервиса для той же улицы нарушений ${f.violations}.</p>
</div>
<div class="col" style="left:760px;top:290px;width:1060px">
  <p class="chart-title">785 нарушений по видам объектов: у посадки их бывает несколько</p>
  ${hbars(AUDIT, { width: 1060, row: 64, labelW: 290 })}
</div>`,
  },
  // 6. Скорость
  {
    bg: 'light',
    html: `
<h1 class="title">18 улиц пилота без ручных правок</h1>
<div class="col" style="left:96px;top:250px;width:1728px">
  <p class="chart-title">Минуты прогона по 18 улицам из 19, медиана ${f.minutes_median}. Docker на Linux, 16 потоков, две улицы параллельно</p>
  ${timeColumns(STREETS, { width: 1728, height: 660 })}
</div>
<p class="foot dark-ink">Демонстрационный фрагмент улицы Берзарина: ${DEMO.placements} посадок за ${DEMO.seconds} с. Полный цикл на машине разработки: чтение, план, проверка, запись DXF.</p>`,
  },
  // 7. Эффект
  {
    bg: 'dark',
    html: `
<h1 class="title">Тень и защита от пыли на 18 улицах</h1>
<div class="col" style="left:96px;top:280px;width:1050px">
  <p class="chart-title light">Борта под кронами и кустарником, %: <span style="color:${C.lav}">было</span> и <span style="color:${C.rose}">с планом сервиса</span>, 7 улиц с наибольшим приростом</p>
  ${beforeAfter(topCurb, { width: 1050, row: 86, labelW: 300 })}
</div>
<dl class="facts" style="left:1250px;top:280px;width:600px">
  <dt>${f.trees} и ${f.shrubs}</dt><dd>деревьев и кустов в плане: в аллеях 791 дерево, группами на газоне 2 813, в изгородях 13 700 кустов</dd>
  <dt>${f.effect_curb.replace(' длины бортов', '')}</dt><dd>длины бортов под кронами и кустарником, прирост ${f.effect_curb_m}</dd>
  <dt>${f.effect_canopy_m2}</dt><dd>взрослых крон: ${f.effect_canopy}</dd>
  <dt>${f.effect_tiers}</dt><dd>деревьев с кустарником под кроной; «было» - оценка по меткам чертежа</dd>
</dl>`,
  },
  // 8. Правка
  {
    bg: 'light',
    html: `
<h1 class="title">План можно поправить в браузере</h1>
<div class="crop framed" style="left:96px;top:270px;width:1240px;height:700px">${img('edit.png', 'fill', 'object-position:50% 30%;transform:scale(1.9);transform-origin:47% 42%')}</div>
<ol class="mini" style="left:1400px;top:300px;width:430px">
  <li>Тянем посадку мышью или клавишами.</li>
  <li>Сервис на лету проверяет новое место теми же нормами: красная выноска - до соседа или сети меньше нормы.</li>
  <li>Кнопка пересборки переписывает DXF и объяснения.</li>
</ol>`,
  },
  // 9. 3D и кадры
  {
    bg: 'dark',
    html: `
<h1 class="title">Участок в 3D по тем же координатам</h1>
<div class="crop framed" style="left:96px;top:270px;width:1060px;height:600px">${img('scene-kust-1.jpg', 'fill', 'object-position:50% 50%;transform:scale(1.14);transform-origin:40% 62%')}</div>
<div class="crop framed" style="left:1200px;top:270px;width:624px;height:600px">${img('scene-kust-2.jpg', 'fill', 'object-position:55% 50%;transform:scale(1.08);transform-origin:55% 55%')}</div>
<p class="foot">Здания по этажности из подписей чертежа, кроны по виду и возрасту, солнце по часу над Москвой. Кадры посадки и улицы подбираются автоматически: объект виден, дома и соседние кроны не заслоняют.</p>`,
  },
  // 10. Фото
  {
    bg: 'light',
    html: `
<h1 class="title">Улица после посадки</h1>
<div class="crop framed" style="left:96px;top:250px;width:1130px;height:636px">${img('street-photo-1.jpg', 'fill')}
  <div class="inset">${img('street-src-1.jpg', 'fill')}<span>кадр 3D-вида</span></div></div>
<div class="crop framed" style="left:1260px;top:250px;width:564px;height:304px">${img('street-photo-2.jpg', 'fill')}<span class="tag">режим «фон и деревья»</span></div>
<div class="crop framed" style="left:1260px;top:582px;width:564px;height:304px">${img('street-photo-3.jpg', 'fill')}<span class="tag">только по плану</span></div>
<p class="foot dark-ink">Qwen-Image-2.1 на локальной видеокарте 6 ГБ, около 80 с на кадр; модели вне Docker-образа, план от них не зависит. Деревья стоят в точках 3D-кадра, фото - иллюстрация, норм на нём нет. Фон и деревья вне плана - только в режиме «фон и деревья».</p>`,
  },
  // 11. Новые фасады. Снимки modern-*.jpg - фото сервиса с галочкой «новые фасады» из
  // var/runs/<прогон>/photos, в shots/ кладутся руками (кадр до 1600 x 900).
  {
    bg: 'light',
    html: `
<h1 class="title">Режим «новые фасады»</h1>
<div class="trio" style="top:270px">
  <figure><div class="crop framed">${img('modern-src.jpg', 'fill')}</div><figcaption>кадр 3D-вида</figcaption></figure>
  <span class="arrow ink">→</span>
  <figure><div class="crop framed">${img('modern-before.jpg', 'fill')}</div><figcaption>фото: фасады как в съёмке</figcaption></figure>
  <span class="arrow ink">→</span>
  <figure><div class="crop framed">${img('modern-after.jpg', 'fill')}</div><figcaption>фото: новые фасады</figcaption></figure>
</div>
<div class="trio" style="top:660px">
  <figure><div class="crop framed">${img('modern-street-src.jpg', 'fill')}</div><figcaption>кадр 3D-вида, кроны 25 лет</figcaption></figure>
  <span class="arrow ink">→</span>
  <figure><div class="crop framed">${img('modern-street.jpg', 'fill')}</div><figcaption>фото: новые фасады</figcaption></figure>
  <p class="trio-note">Дом сохраняет пятно, высоту и этажность, меняются только материалы: керамогранит, клинкер, витрины на первом этаже. Посадки, ограды и люди остаются на своих местах.</p>
</div>`,
  },
  // 12. Что получает город
  {
    bg: 'light',
    html: `
<h1 class="title">Что получает город</h1>
<table class="compare" style="left:96px;top:270px;width:1728px">
  <thead><tr><th></th><th>Сейчас</th><th>С сервисом green</th></tr></thead>
  <tbody>
    <tr><td>Проверка отступов</td><td>вручную по чертежу сетей</td><td>${f.rules_distance} нормы расстояний на каждое место, ${f.violations} нарушений на 18 улицах</td></tr>
    <tr><td>Время на улицу</td><td>подбор мест вручную по чертежу</td><td>медиана ${f.minutes_median} мин при рамке заказчика 60 мин, фрагмент ${DEMO.seconds} с</td></tr>
    <tr><td>Обоснование для согласования</td><td>пояснительная записка</td><td>у каждой посадки замер, акт, пункт и цитата</td></tr>
    <tr><td>Проверка готового проекта</td><td>экспертиза вручную</td><td>нормоконтроль за 162 с, у нарушения - сколько метров не хватает</td></tr>
    <tr><td>Новая редакция норм</td><td>сверка по новой редакции вручную</td><td>правка файла норм без программиста; СП 42.13330 редакций 2016 и 2026 уже в своде</td></tr>
  </tbody>
</table>
<p class="foot dark-ink">Озеленение улицы районного значения стоит ${CUSTOMER.costPerHa} на гектар (ориентир заказчика). В принятом плане Берзарина 159 нарушений отступа до силового кабеля: при посадке это риск повредить сеть.</p>`,
  },
  // 13. Внедрение
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
  <div class="box core">Одно ядро<small>CLI, API и веб вызывают один сценарий PlanSite</small></div>
</div>
<pre class="cmd" style="left:96px;top:690px">docker compose up --build
green run улица.dxf --profile barriers --set spacing_m=6</pre>
<p class="foot" style="width:960px">Образ на Ubuntu 26.04: по ТЗ МосТех.ОС близка к Ubuntu. Расчёту не нужны GPU и сеть. ${f.params} параметров, 5 профилей; 2 077 тестов бэкенда и 312 фронтенда. Манифесты Kubernetes проверены kubeconform.</p>
<div class="crop framed" style="left:1130px;top:280px;width:694px;height:560px">${img('swagger.png', 'fill', 'object-position:0 0')}</div>`,
  },
  // 14. Границы и внедрение (08-limitations, п. 8.2; ТЗ, разд. 4 и 9)
  {
    bg: 'light',
    html: `
<h1 class="title">Границы сервиса и путь внедрения</h1>
<div class="col" style="left:96px;top:290px;width:820px">
  <p class="chart-title">Чего сервис не делает</p>
  <ul class="plain">
    <li>Вырубку и пересадку не назначает: на плотных улицах деревьев в плане меньше, чем в проекте с вырубкой.</li>
    <li>Площадки, дорожки и малые формы сквера не проектирует.</li>
    <li>Кадастр и зонирование из слоёв ГИС учитывает как сведения, а не как запрет.</li>
    <li>Вход - DXF; DWG - через ODA File Converter, LibreDWG теряет области REGION.</li>
    <li>Результат открыт в LibreCAD под Ubuntu; в nanoCAD не проверялся.</li>
  </ul>
</div>
<div class="col" style="left:1000px;top:290px;width:824px">
  <p class="chart-title">Как внедрить в контуре ДПиООС</p>
  <ol class="mini" style="position:static">
    <li>Пилот на ресурсах департамента: образ Docker без сети и GPU.</li>
    <li>Проектировщик загружает улицу, правит план в браузере, выгружает DXF и объяснения.</li>
    <li>Нормоконтроль проектов подрядчиков: green audit.</li>
    <li>Интеграция с системами департамента через /api/v1 по OpenAPI.</li>
  </ol>
</div>`,
  },
  // 15. Финал
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
svg .val { font: 700 22px Montserrat; fill: ${C.night}; paint-order: stroke; stroke: #F3F1F6; stroke-width: 6px }
.dark svg .val { fill: #fff; stroke: none }
svg .sm { font-size: 18px }
svg .ref { font: 600 20px Montserrat; fill: ${C.plum} }
svg .donut-n { font: 800 84px Montserrat; fill: ${C.pink} }
svg .donut-l { font: 600 20px Montserrat; fill: #3c3548 }
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
.steps span { display: block; font-size: 24px; line-height: 1.45; color: #3c3548 }
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
.trio { position: absolute; left: 96px; width: 1728px; display: flex; align-items: flex-start; gap: 22px }
.trio figure { margin: 0 }
.trio .crop { position: relative; width: 520px; height: 292px }
.trio .crop.big { width: 820px; height: 461px }
.inset { position: absolute; left: 22px; bottom: 22px; width: 352px; height: 198px; border-radius: 12px; overflow: hidden;
  border: 3px solid #fff; box-shadow: 0 10px 30px rgba(0,0,0,.35) }
.inset span, .tag { position: absolute; left: 12px; bottom: 10px; padding: 4px 12px; border-radius: 999px;
  background: rgba(28,29,34,.8); color: #fff; font-size: 18px; font-weight: 600 }
.trio figcaption { margin-top: 12px; font-size: 20px; font-weight: 600; color: ${C.mute} }
.trio .arrow.ink { align-self: center; margin-top: -34px; font-size: 48px }
.trio-note { width: 520px; margin: 0 0 0 20px; align-self: center; font-size: 24px; font-weight: 500; line-height: 1.45; color: #3c3548 }
.compare { border-collapse: collapse; font-size: 26px }
.compare th { text-align: left; font-size: 24px; font-weight: 700; color: ${C.plum}; padding: 0 24px 18px 0 }
.compare td { padding: 22px 24px 22px 0; border-top: 2px solid ${C.blush}; line-height: 1.35; vertical-align: top }
.compare td:first-child { font-weight: 700; color: ${C.night}; width: 400px }
.compare td:nth-child(2) { color: ${C.mute}; width: 440px }
.compare td:nth-child(3) { position: relative; padding-left: 26px; font-weight: 600; color: ${C.ink} }
.compare td:nth-child(3)::before { content: ''; position: absolute; left: 0; top: 34px; width: 12px; height: 12px;
  border-radius: 50%; background: ${C.pink} }
.plain { margin: 0; padding: 0; list-style: none }
.plain li { position: relative; padding-left: 28px; margin-bottom: 26px; font-size: 26px; font-weight: 500; line-height: 1.4; color: #3c3548 }
.plain li::before { content: ''; position: absolute; left: 0; top: 14px; width: 12px; height: 12px; border-radius: 50%; background: ${C.lav} }
.arch { display: flex; align-items: center; gap: 34px }
.arch .stack { display: grid; gap: 18px }
.arch .box { width: 400px; padding: 22px 26px; border-radius: 16px; background: rgba(255,255,255,.1);
  border: 1.5px solid rgba(255,255,255,.28); font-size: 28px; font-weight: 700 }
.arch .box small { display: block; margin-top: 6px; font-size: 20px; font-weight: 500; color: rgba(255,255,255,.75) }
.arch .core { background: ${C.pink}; border-color: ${C.pink}; width: 420px }
.arch .core small { color: rgba(255,255,255,.9) }
.arch .arrow { margin: 0 }
.cmd { margin: 0; padding: 20px 30px; border-radius: 14px; background: rgba(0,0,0,.35); font: 600 24px/1.5 'JetBrains Mono', monospace; color: #fff }
.final { position: absolute; left: 120px; top: 360px; width: 1000px }
.final .brand { margin: 0; font-size: 190px; font-weight: 800; letter-spacing: -0.04em; line-height: 1 }
.final .lead { margin: 18px 0 40px; font-size: 40px; font-weight: 600 }
.final .body { color: rgba(255,255,255,.86); font-size: 28px }
.num { position: absolute; right: 64px; bottom: 34px; font-size: 20px; font-weight: 600; color: ${C.plum} }
.dark .num, .city .num { color: #fff }
.final { width: 1300px }
.final .lead { text-wrap: balance }
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
