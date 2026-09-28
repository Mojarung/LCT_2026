// 03 маршрут: 15 этапов змейкой, импульс проходит каждый узел; в конце узлы слетаются
// в линейку глав наверху, и по этой линейке идёт весь дальнейший рассказ
(function () {
  const FILM = window.FILM, lib = FILM.lib, P = lib.pal, G = FILM.G, E = lib.ease;
  const clamp = lib.clamp;
  const DUR = 18;

  // этап, подпись, глава рассказа (индекс в G.CHAPTERS)
  const STAGES = [
    ['Конвертация', 'DWG → DXF: ODA или LibreDWG', 0],
    ['Склейка комплекта', 'XREF между файлами', 0],
    ['Чтение', 'ремонт строк, блоки до 8 уровней', 0],
    ['Классификация', '76 правил слоёв, 37 классов', 0],
    ['Карта покрытий', 'грунт по замкнутым граням', 0],
    ['Кандидаты', 'аллея вдоль борта, сетка по газону', 2],
    ['Проверка норм', '46 отступов, допуск 1 мм', 1],
    ['Портфель', 'до 8 раскладок, лучший индекс', 5],
    ['Подбор видов', 'MILP, квоты 10-20-30', 3],
    ['Кустарники', 'группы 3 × 3 на местах, пустых по квотам', 3],
    ['Проверка плана', '13 кодов нарушений', 5],
    ['Индекс качества', '10 слагаемых, ценность посадки', 5],
    ['Объяснения', 'из трассы правил, без LLM', 4],
    ['Запись DXF', '9 слоёв GREEN_*', 6],
    ['Сверка', 'blake2b каждой исходной сущности', 6],
  ];
  const ROWS = [370, 610, 850];
  const XS = [250, 605, 960, 1315, 1670];
  const NODES = STAGES.map((s, i) => {
    const row = Math.floor(i / 5);
    const col = row % 2 === 0 ? i % 5 : 4 - (i % 5);
    return { x: XS[col], y: ROWS[row], name: s[0], cap: s[1], ch: s[2], row };
  });
  const T0 = 2.0, STEP = 0.6;
  const litAt = (i) => T0 + i * STEP;
  const COLLAPSE = [15.4, 1.8];
  // куда слетаются узлы: центр своей главы на линейке (координаты из G.chapters)
  const rulerX = (ch) => 1040 + ((1860 - 1040) / G.CHAPTERS.length) * (ch + 0.5);

  function pathPoint(u) {
    const n = NODES.length - 1;
    const f = clamp(u) * n;
    const i = Math.min(n - 1, Math.floor(f));
    const q = f - i;
    const a = NODES[i], b = NODES[i + 1];
    if (a.row === b.row) return [lib.lerp(a.x, b.x, q), a.y];
    const side = a.row % 2 === 0 ? 1 : -1;
    const cy = (a.y + b.y) / 2, r = (b.y - a.y) / 2;
    const ang = -Math.PI / 2 + q * Math.PI;
    return [a.x + side * Math.cos(ang) * r * 0.9, cy + Math.sin(ang) * r];
  }

  FILM.slide({
    id: 'pipeline',
    mode: 'blue',
    dur: DUR,
    tr: { kind: 'lens', dur: 1.5, x: 960, y: 540, ring: P.ink },
    draw(ctx, t) {
      lib.blueprint(ctx, { noise: 0, center: [960, 640] });
      const cq = G.seg(t, COLLAPSE[0], COLLAPSE[1], 'inOutCubic');
      const keep = 1 - G.seg(t, COLLAPSE[0], 0.6, 'linear');
      ctx.save();
      ctx.globalAlpha *= keep;
      G.kicker(ctx, 'МАРШРУТ ПРОГОНА', 120, 106, { color: P.lavender, p: G.seg(t, 0.2, 0.6, 'linear') });
      G.text(ctx, 'Пятнадцать этапов, один сценарий', 116, 170, { size: 60, weight: 300, color: P.lineWhite, p: G.seg(t, 0.3, 1.0, 'linear') });
      G.para(ctx, 'CLI, HTTP API и веб-интерфейс вызывают один и тот же сценарий PlanSite. Ядро без фреймворков, границы слоёв держит import-linter.', 120, 240, { size: 24, weight: 400, maxW: 1600, lh: 34, color: P.lavender, p: G.seg(t, 0.8, 1.6, 'linear') });
      for (let i = 0; i + 1 < NODES.length; i++) {
        const a = NODES[i], b = NODES[i + 1];
        const q = G.seg(t, 0.5 + i * 0.05, 0.6, 'outCubic');
        if (a.row === b.row) {
          G.link(ctx, a.x + 62 * Math.sign(b.x - a.x), a.y, b.x - 62 * Math.sign(b.x - a.x), b.y, { p: q, bend: 0, alpha: 0.5 });
        } else {
          const side = a.row % 2 === 0 ? 1 : -1;
          ctx.save();
          ctx.strokeStyle = lib.rgba(P.lavender, 0.5);
          ctx.lineWidth = 1.5;
          ctx.beginPath();
          const cy = (a.y + b.y) / 2, r = (b.y - a.y) / 2;
          ctx.ellipse(a.x, cy, r * 0.9, r, 0, -Math.PI / 2, -Math.PI / 2 + Math.PI * q * side, side < 0);
          ctx.stroke();
          ctx.restore();
        }
      }
      ctx.restore();
      // узлы: на сворачивании летят к своей главе и превращаются в точки линейки
      NODES.forEach((n, i) => {
        const appear = G.seg(t, 0.4 + i * 0.06, 0.35, 'linear');
        const lit = G.seg(t, litAt(i), 0.3, 'outCubic');
        const c = clamp(cq * 1.3 - i * 0.02);
        const e = E.inOutCubic(c);
        const x = lib.lerp(n.x, rulerX(n.ch), e);
        const y = lib.lerp(n.y, 52, e);
        const r = lib.lerp(56, 5, e);
        if (c < 1) {
          G.node(ctx, x, y, r, { p: appear, lit: lit * (1 - c), litColor: i === NODES.length - 1 ? P.magenta : P.paleBlue });
          G.text(ctx, String(i + 1).padStart(2, '0'), x, y + 11 * (r / 56), { size: 30 * (r / 56), weight: 400, family: G.MONO, color: P.lineWhite, align: 'center', alpha: appear * (1 - c) });
        }
        const fl = (t - litAt(i)) / 0.5;
        if (fl > 0 && fl < 1) {
          lib.glowDot(ctx, n.x, n.y - 56, 6, { intensity: 1 - fl, rays: 8 });
          G.ring(ctx, n.x, n.y, 80, t, litAt(i), { color: P.paleBlue, dur: 0.5 });
        }
        const lq = G.seg(t, litAt(i) - 0.1, 0.6, 'linear') * keep;
        G.text(ctx, n.name, n.x, n.y + 96, { size: 25, weight: 500, color: P.lineWhite, align: 'center', p: lq });
        G.text(ctx, n.cap, n.x, n.y + 126, { size: 18, weight: 400, family: G.MONO, color: P.lavender, align: 'center', p: lq, alpha: 0.9 });
      });
      // импульс по змейке, потом бегущие точки
      const u = (t - T0) / (STEP * (NODES.length - 1));
      if (keep > 0) {
        if (u > 0 && u < 1) {
          const [px, py] = pathPoint(u);
          lib.glowDot(ctx, px, py, 7, { rays: 8, intensity: 1.1 });
        }
        if (u >= 1) {
          for (let k = 0; k < 3; k++) {
            const v = (((t - T0 - STEP * 14) / 7 + k / 3) % 1 + 1) % 1;
            const [px, py] = pathPoint(v);
            lib.glowDot(ctx, px, py, 4, { rays: 0, glow: 5, intensity: 0.7 * keep });
          }
        }
      }
      // линейка глав собирается из узлов
      G.chapters(ctx, t, 0, { blue: true, alpha: G.seg(t, COLLAPSE[0] + 0.8, 0.8, 'linear'), dur: 1e9 });
    },
  });
})();
