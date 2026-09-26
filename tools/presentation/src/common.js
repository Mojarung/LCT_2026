/*
 * common.js : общее для всех слайдов.
 *   - шрифты, абзацы с переносом, заголовки с проявлением по буквам;
 *   - одна улица в плане (20 px = 1 м), которую слайды показывают с разных сторон:
 *     на бумаге видна поверхность, на синьке видны сети под ней;
 *   - деревья, кустарники, опоры, узлы схем;
 *   - мини-версия проверки отступов: кандидаты и причины отказа считаются по той же геометрии.
 */
(function () {
  'use strict';

  const FILM = window.FILM;
  const lib = FILM.lib;
  const P = lib.pal;
  const E = lib.ease;
  const TAU = Math.PI * 2;
  const clamp = lib.clamp;
  const lerp = lib.lerp;
  const G = (FILM.G = {});

  G.BEAT = 0.5; // 120 ударов в минуту
  G.SANS = '"Segoe UI Variable Display", "SF Pro Display", "Helvetica Neue", Inter, "Noto Sans", "DejaVu Sans", system-ui, sans-serif';
  G.MONO = 'ui-monospace, "Cascadia Mono", "JetBrains Mono", Consolas, "DejaVu Sans Mono", monospace';
  G.M = 20; // пикселей в метре на плане улицы

  // палитра презентации поверх палитры движка
  G.C = {
    lawn: '#C9D6B0',
    lawnDeep: '#A9BC8C',
    crown: '#8FAF6E',
    crownDeep: '#5E8248',
    crownPale: '#B8CE98',
    conifer: '#4F7A57',
    coniferDeep: '#2F5A3F',
    shrub: '#9DB77A',
    shrubDeep: '#6C8F52',
    asphalt: '#D9CFBF',
    asphaltDeep: '#BDB09C',
    tile: '#E9DDC4',
    roof: '#D8C3A0',
    roofDeep: '#B89C74',
    // сети: на синьке линии, на бумаге рентгеновские вставки
    power: '#FF3D98',
    water: '#6FB7FF',
    gas: '#F2C94C',
    heat: '#FF8A5B',
    sewer: '#9CE6C6',
    telecom: '#C8C1EF',
    // интерфейс: графит и кость
    graphite: '#1D1F22',
    graphite2: '#26292D',
    graphite3: '#33373C',
    bone: '#E9E3D6',
    boneDim: '#A8A295',
    signal: '#D9F26B',
  };
  const C = G.C;

  // ---------------------------------------------------------------------------
  // Время
  // ---------------------------------------------------------------------------

  G.seg = (t, t0, dur, e) => lib.seg(t, t0, t0 + dur, e || 'outExpo');
  // появление с перелётом (outBack) за 3 кадра по 24 fps, как в стиле фильма
  G.pop = (t, t0, dur) => {
    const d = dur || 0.18;
    if (t <= t0) return 0;
    return E.outBack(clamp((t - t0) / d));
  };

  // ---------------------------------------------------------------------------
  // Текст
  // ---------------------------------------------------------------------------

  const measureCache = new Map();
  function font(o) {
    return `${o.italic ? 'italic ' : ''}${o.weight || 300} ${o.size || 42}px ${o.family || G.SANS}`;
  }
  G.font = font;

  function measure(ctx, str, f, tracking) {
    const key = f + '|' + tracking + '|' + str;
    let v = measureCache.get(key);
    if (v == null) {
      ctx.save();
      ctx.font = f;
      if ('letterSpacing' in ctx) ctx.letterSpacing = (tracking || 0) + 'px';
      v = ctx.measureText(str).width;
      ctx.restore();
      if (measureCache.size > 4000) measureCache.clear();
      measureCache.set(key, v);
    }
    return v;
  }
  G.measure = (ctx, str, o) => measure(ctx, str, font(o || {}), (o && o.tracking) || 0);

  function wrap(ctx, str, f, tracking, maxW) {
    const key = 'wrap|' + f + '|' + maxW + '|' + str;
    let v = measureCache.get(key);
    if (v) return v;
    const out = [];
    for (const para of String(str).split('\n')) {
      const words = para.split(' ');
      let line = '';
      for (const w of words) {
        const test = line ? line + ' ' + w : w;
        if (line && measure(ctx, test, f, tracking) > maxW) {
          out.push(line);
          line = w;
        } else line = test;
      }
      out.push(line);
    }
    measureCache.set(key, out);
    return out;
  }

  /**
   * text(ctx, str, x, y, o) : одна строка. o.p : доля проявления (буквы всплывают по очереди).
   * size, weight, color, alpha, align, family, tracking, baseline.
   */
  G.text = (ctx, str, x, y, o = {}) => {
    const s = String(str);
    if (!s) return 0;
    const f = font(o);
    const tr = o.tracking || 0;
    const w = measure(ctx, s, f, tr);
    let x0 = x;
    if (o.align === 'center') x0 = x - w / 2;
    else if (o.align === 'right') x0 = x - w;
    ctx.save();
    ctx.font = f;
    ctx.fillStyle = o.color || P.ink;
    ctx.textBaseline = o.baseline || 'alphabetic';
    if ('letterSpacing' in ctx) ctx.letterSpacing = tr + 'px';
    const alpha = o.alpha != null ? o.alpha : 1;
    if (o.p == null || o.p >= 1) {
      ctx.globalAlpha *= alpha;
      ctx.fillText(s, x0, y);
    } else if (o.p > 0) {
      // по буквам: каждая поднимается на 14 px и проявляется, волна идёт слева направо
      const n = s.length;
      const spread = 0.55;
      let cx = x0;
      const base = ctx.globalAlpha;
      for (let i = 0; i < n; i++) {
        const ch = s[i];
        const cw = measure(ctx, ch, f, tr);
        const q = clamp((o.p - (i / n) * spread) / (1 - spread));
        if (q > 0) {
          const e = E.outCubic(q);
          ctx.globalAlpha = base * alpha * e;
          ctx.fillText(ch, cx, y + (1 - e) * (o.rise != null ? o.rise : 14));
        }
        cx += cw;
      }
    }
    ctx.restore();
    return w;
  };

  /**
   * para(ctx, str, x, y, o) : абзац с переносом по ширине o.maxW, межстрочный o.lh.
   * o.p : проявление строками. Возвращает высоту.
   */
  G.para = (ctx, str, x, y, o = {}) => {
    const f = font(o);
    const tr = o.tracking || 0;
    const lines = wrap(ctx, str, f, tr, o.maxW || 800);
    const lh = o.lh || (o.size || 32) * 1.32;
    const n = lines.length;
    for (let i = 0; i < n; i++) {
      const q = o.p == null ? 1 : clamp((o.p * (n + 1.2) - i) / 1.2);
      if (q <= 0) continue;
      G.text(ctx, lines[i], x, y + i * lh, Object.assign({}, o, { p: q >= 1 ? null : q, rise: 10 }));
    }
    return n * lh;
  };
  G.lines = (ctx, str, o = {}) => wrap(ctx, str, font(o), o.tracking || 0, o.maxW || 800);

  /** kicker : мелкая подпись над заголовком, моноширинная, разрядка. */
  G.kicker = (ctx, str, x, y, o = {}) =>
    G.text(ctx, str, x, y, Object.assign({ size: 22, weight: 500, family: G.MONO, tracking: 3, alpha: 0.75 }, o));

  /** Заголовок слайда: кикер, крупная строка, линейка под ней с делениями. */
  G.heading = (ctx, t, x, y, kick, title, o = {}) => {
    const blue = o.blue;
    const col = o.color || (blue ? P.lineWhite : P.ink);
    const sub = o.sub || (blue ? P.lavender : P.inkSoft);
    const t0 = o.t0 || 0;
    if (kick) G.kicker(ctx, kick, x, y - 64, { color: sub, p: G.seg(t, t0, 0.6, 'linear') });
    G.text(ctx, title, x, y, { size: o.size || 64, weight: o.weight || 300, color: col, p: G.seg(t, t0 + 0.1, 0.9, 'linear'), tracking: -0.5 });
    const L = o.rule != null ? o.rule : 520;
    if (L > 0) {
      const q = G.seg(t, t0 + 0.25, 0.8);
      lib.ticks(ctx, x, y + 26, { length: L * q, n: Math.max(1, Math.round(20 * q)), len: 8, major: 5, majorLen: 16, color: sub, alpha: 0.55, width: 1.5 });
    }
  };

  // ---------------------------------------------------------------------------
  // Выноска-карточка на бумаге и на синьке
  // ---------------------------------------------------------------------------

  G.card = (ctx, x, y, w, h, o = {}) => {
    const q = o.p != null ? o.p : 1;
    if (q <= 0) return;
    ctx.save();
    const e = E.outBack(clamp(q));
    ctx.translate(x + w / 2, y + h / 2);
    ctx.scale(lerp(0.92, 1, e), lerp(0.92, 1, e));
    ctx.globalAlpha *= clamp(q * 2);
    ctx.translate(-(x + w / 2), -(y + h / 2));
    if (o.blue) {
      ctx.fillStyle = lib.rgba(P.navyLight, 0.92);
      ctx.fillRect(x, y, w, h);
      ctx.strokeStyle = lib.rgba(P.lavender, 0.7);
      ctx.lineWidth = 2;
      ctx.strokeRect(x, y, w, h);
      ctx.strokeStyle = lib.rgba(P.lavender, 0.3);
      ctx.lineWidth = 1;
      ctx.strokeRect(x + 7, y + 7, w - 14, h - 14);
    } else {
      ctx.fillStyle = lib.rgba(o.fill || P.white, 0.94);
      ctx.fillRect(x, y, w, h);
      lib.inkPath(ctx, lib.rectPts(x, y, w, h, 30), { closed: true, width: 2.4, seed: o.seed || 3, wobble: 1.1 });
    }
    ctx.restore();
  };

  // ---------------------------------------------------------------------------
  // Улица в плане. Мир = кадр 1920x1080 при камере 1. 20 px = 1 м.
  // ---------------------------------------------------------------------------

  const S = {
    facadeTop: 230,
    walkTop: [230, 350],
    lawnA: [350, 470],
    curbA: 470,
    road: [470, 690],
    curbB: 690,
    lawnB: [690, 790],
    walkB: [790, 900],
    facadeBot: 920,
  };
  G.street = S;

  // здания: верхний ряд и нижний ряд, со дворами-проездами
  S.buildings = [
    [[-40, 40], [360, 40], [360, 230], [-40, 230]],
    [[430, 70], [880, 70], [880, 230], [430, 230]],
    [[960, 20], [1340, 20], [1340, 120], [1250, 120], [1250, 230], [960, 230]],
    [[1420, 60], [1960, 60], [1960, 230], [1420, 230]],
    [[-40, 920], [520, 920], [520, 1120], [-40, 1120]],
    [[600, 920], [1080, 920], [1080, 1010], [1180, 1010], [1180, 1120], [600, 1120]],
    [[1260, 920], [1960, 920], [1960, 1120], [1260, 1120]],
  ];
  // опоры освещения у борта
  S.poles = [];
  for (const x of [180, 660, 1140, 1620]) S.poles.push([x, S.curbA - 18]);
  for (const x of [420, 900, 1380, 1860]) S.poles.push([x, S.curbB + 18]);

  // подземные сети: ломаные в мировых координатах
  S.nets = [
    { key: 'power', name: 'силовой кабель', color: C.power, pts: [[-40, 392], [600, 392], [680, 300], [1960, 300]] },
    { key: 'telecom', name: 'кабель связи', color: C.telecom, pts: [[-40, 320], [1960, 320]] },
    { key: 'water', name: 'водопровод', color: C.water, pts: [[-40, 764], [700, 764], [780, 846], [1960, 846]] },
    { key: 'gas', name: 'газопровод', color: C.gas, pts: [[-40, 872], [1960, 872]] },
    { key: 'heat', name: 'теплосеть', color: C.heat, pts: [[-40, 636], [1960, 636]], channel: 14 },
    { key: 'sewer', name: 'канализация', color: C.sewer, pts: [[-40, 560], [1960, 560]], wells: [240, 720, 1200, 1680] },
  ];

  // расстояние от точки до ломаной
  function distPoly(x, y, pts) {
    let best = Infinity;
    for (let i = 0; i + 1 < pts.length; i++) {
      const [x1, y1] = pts[i], [x2, y2] = pts[i + 1];
      const dx = x2 - x1, dy = y2 - y1;
      const L2 = dx * dx + dy * dy || 1;
      const u = clamp(((x - x1) * dx + (y - y1) * dy) / L2);
      const d = Math.hypot(x - (x1 + dx * u), y - (y1 + dy * u));
      if (d < best) best = d;
    }
    return best;
  }
  G.distPoly = distPoly;
  G.nearestOnPoly = (x, y, pts) => {
    let best = Infinity, bp = pts[0];
    for (let i = 0; i + 1 < pts.length; i++) {
      const [x1, y1] = pts[i], [x2, y2] = pts[i + 1];
      const dx = x2 - x1, dy = y2 - y1;
      const u = clamp(((x - x1) * dx + (y - y1) * dy) / (dx * dx + dy * dy || 1));
      const px = x1 + dx * u, py = y1 + dy * u;
      const d = Math.hypot(x - px, y - py);
      if (d < best) { best = d; bp = [px, py]; }
    }
    return bp;
  };

  // ---------------------------------------------------------------------------
  // Кандидаты и отбор по отступам (метры из config/rules.yaml, подставляются в G.RULES)
  // ---------------------------------------------------------------------------

  G.RULES = {
    power: 2, telecom: 2, water: 2, gas: 1.5, heat: 2, sewer: 1.5, pole: 4, curb: 2, walk: 0.7, facade: 5,
  };

  G.candidates = (() => {
    const out = [];
    const rows = [
      { y: 410, lawn: S.lawnA },
      { y: 740, lawn: S.lawnB },
    ];
    let id = 0;
    for (const row of rows) {
      for (let x = 60; x <= 1860; x += 120) {
        const c = { id: id++, x, y: row.y, row: row === rows[0] ? 'A' : 'B', fails: [] };
        for (const n of S.nets) {
          const d = distPoly(x, row.y, n.pts) / G.M - (n.channel ? n.channel / 2 / G.M : 0);
          const need = G.RULES[n.key];
          if (d < need) c.fails.push({ what: n.name, key: n.key, d, need });
        }
        for (const [px, py] of S.poles) {
          const d = Math.hypot(px - x, py - row.y) / G.M;
          if (d < G.RULES.pole) c.fails.push({ what: 'опора освещения', key: 'pole', d, need: G.RULES.pole, at: [px, py] });
        }
        c.ok = c.fails.length === 0;
        out.push(c);
      }
    }
    return out;
  })();

  // ---------------------------------------------------------------------------
  // Рисование улицы на бумаге
  // ---------------------------------------------------------------------------

  const layerCache = new Map();
  /** Растровый кэш тяжёлого статичного слоя: 3 варианта «кипения» по кругу. */
  G.cachedCanvas = (key, drawFn, o = {}) => {
    const Sx = FILM.S * (o.over || 1);
    const variant = o.boil === false ? 0 : lib.boil(lib.T) % 3;
    const k = key + '|' + Sx.toFixed(3) + '|' + variant;
    let c = layerCache.get(k);
    if (!c) {
      c = FILM.makeCanvas(Math.round(FILM.W * Sx), Math.round(FILM.H * Sx));
      const g = c.getContext('2d');
      g.scale(Sx, Sx);
      const saved = FILM.frameT, sun = G.sunA;
      FILM.frameT = variant / 12 + 0.001;
      G.sunA = 0.9;
      drawFn(g);
      FILM.frameT = saved;
      G.sunA = sun;
      layerCache.set(k, c);
      if (layerCache.size > 80) layerCache.delete(layerCache.keys().next().value);
    }
    return c;
  };
  G.cached = (ctx, key, drawFn, o = {}) => ctx.drawImage(G.cachedCanvas(key, drawFn, o), 0, 0, FILM.W, FILM.H);

  function rectPoly(x0, y0, x1, y1) {
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]];
  }
  G.rectPoly = rectPoly;

  /** Поверхность улицы: здания, тротуары, газоны, борта, проезжая часть. */
  G.drawSurface = (g, o = {}) => {
    const W = 1920;
    // o.part: 'road' | 'walks' | 'lawns' | 'buildings'; без него вся поверхность
    const on = (p) => !o.part || o.part === p;
    if (on('road')) {
    // проезжая часть
    g.fillStyle = C.asphalt;
    g.fillRect(-60, S.road[0], W + 120, S.road[1] - S.road[0]);
    lib.stipple(g, rectPoly(-60, S.road[0], W + 60, S.road[1]), { spacing: 9, r: [0.6, 1.3], color: P.inkSoft, alpha: 0.35, seed: 41, density: 0.55 });
    // осевая разметка
    for (let x = -20; x < W; x += 110) lib.inkLine(g, x, 580, x + 60, 580, { width: 3, color: P.white, alpha: 0.95, seed: 700 + x, taper: 4 });
    // пешеходный переход
    for (let k = 0; k < 7; k++) {
      const yy = S.road[0] + 16 + k * 30;
      g.fillStyle = lib.rgba(P.white, 0.9);
      g.fillRect(1500, yy, 110, 16);
    }
    }
    if (on('walks')) {
    // тротуары с плиткой
    for (const [y0, y1] of [S.walkTop, S.walkB]) {
      g.fillStyle = C.tile;
      g.fillRect(-60, y0, W + 120, y1 - y0);
      g.strokeStyle = lib.rgba(P.inkFaint, 0.22);
      g.lineWidth = 1;
      g.beginPath();
      for (let x = -20; x < W; x += 40) {
        g.moveTo(x, y0);
        g.lineTo(x, y1);
      }
      for (let y = y0 + 20; y < y1; y += 20) {
        g.moveTo(-60, y);
        g.lineTo(W + 60, y);
      }
      g.stroke();
    }
    for (const y of [S.walkTop[1], S.walkB[0]]) lib.inkLine(g, -40, y, W + 40, y, { width: 2, alpha: 0.8, seed: y + 11, wobble: 1.2 });
    }
    if (on('lawns')) {
    // газоны
    for (const [y0, y1] of [S.lawnA, S.lawnB]) {
      g.fillStyle = C.lawn;
      g.fillRect(-60, y0, W + 120, y1 - y0);
      lib.hatch(g, rectPoly(-60, y0 + 4, W + 60, y1 - 4), { angle: -1.2, spacing: 11, length: [6, 14], gap: [6, 16], width: 1.3, color: C.lawnDeep, alpha: 0.8, seed: y0 });
    }
    }
    if (on('road')) {
    // бортовой камень: двойная линия
    for (const y of [S.curbA, S.curbB]) {
      lib.inkLine(g, -40, y, W + 40, y, { width: 4, seed: y, wobble: 1 });
      lib.inkLine(g, -40, y + (y === S.curbA ? 7 : -7), W + 40, y + (y === S.curbA ? 7 : -7), { width: 1.5, alpha: 0.6, seed: y + 5, wobble: 1 });
    }
    }
    if (on('buildings')) {
    // здания: кровля, штриховка тени, двойной контур
    S.buildings.forEach((poly, i) => {
      g.save();
      g.beginPath();
      lib.tracePath(g, poly, true);
      g.fillStyle = C.roof;
      g.fill();
      g.restore();
      lib.hatch(g, poly, { spacing: 9, width: 1.3, color: C.roofDeep, alpha: 0.75, seed: 90 + i, density: 0.75 });
      lib.inkPath(g, poly, { closed: true, width: 3.2, seed: 50 + i, smooth: false, wobble: 1.2, double: true });
    });
    // тень верхнего ряда зданий на тротуаре: свет сверху слева
    g.save();
    g.globalAlpha *= 0.1;
    g.fillStyle = P.ink;
    for (const poly of S.buildings.slice(0, 4)) {
      const xs = poly.map((p) => p[0]);
      const x0 = Math.min(...xs), x1 = Math.max(...xs);
      g.beginPath();
      g.moveTo(x0, 230);
      g.lineTo(x1, 230);
      g.lineTo(x1 + 26, 262);
      g.lineTo(x0 + 26, 262);
      g.closePath();
      g.fill();
    }
    g.restore();
    // детали кровли: вентшахты и коньки
    const rr = lib.rng(77);
    S.buildings.forEach((poly, i) => {
      const xs = poly.map((p) => p[0]), ys = poly.map((p) => p[1]);
      const x0 = Math.max(Math.min(...xs), -20), x1 = Math.min(Math.max(...xs), 1940);
      const y0 = Math.min(...ys), y1 = Math.min(Math.max(...ys), 1080);
      for (let k = 0; k < 3; k++) {
        const bx = lerp(x0 + 40, x1 - 80, rr()), by = lerp(y0 + 20, y1 - 60, rr());
        g.fillStyle = C.roofDeep;
        g.fillRect(bx, by, 34, 22);
        lib.inkPath(g, lib.rectPts(bx, by, 34, 22, 12), { closed: true, width: 1.8, seed: i * 10 + k, wobble: 0.5, smooth: false });
      }
      lib.inkLine(g, x0 + 20, (y0 + y1) / 2, x1 - 20, (y0 + y1) / 2, { width: 1.4, alpha: 0.45, seed: 300 + i });
    });
    }
    if (on('walks')) {
    // тактильная плитка у перехода и скамейки
    g.fillStyle = '#E8C766';
    g.fillRect(1500, S.walkTop[1] - 16, 110, 12);
    g.fillRect(1500, S.walkB[0] + 4, 110, 12);
    for (const x of [300, 820, 1760]) {
      g.fillStyle = C.roof;
      g.fillRect(x, 262, 70, 16);
      lib.inkPath(g, lib.rectPts(x, 262, 70, 16, 14), { closed: true, width: 1.6, seed: x, smooth: false, wobble: 0.4 });
    }
    // остановка на нижнем тротуаре
    g.fillStyle = lib.rgba(P.paleBlue, 0.6);
    g.fillRect(980, 812, 200, 50);
    lib.hatch(g, lib.rectPts(980, 812, 200, 50, 20), { spacing: 7, width: 1.1, color: P.tealDeep, alpha: 0.5, seed: 5 });
    lib.inkPath(g, lib.rectPts(980, 812, 200, 50, 20), { closed: true, width: 2.4, seed: 44, smooth: false });
    }
    if (on('road')) {
    // стрелки на полосах
    for (const [x, y, d] of [[260, 520, 1], [1180, 520, 1], [760, 640, -1], [1760, 640, -1]]) {
      lib.inkPath(g, [[x - 34 * d, y], [x + 20 * d, y]], { width: 3, color: P.white, taper: 3, seed: x });
      lib.inkPath(g, [[x + 6 * d, y - 12], [x + 24 * d, y], [x + 6 * d, y + 12]], { width: 3, color: P.white, taper: 3, seed: x + 1 });
    }
    // люки канализации
    for (const x of S.nets[5].wells) {
      g.fillStyle = C.asphaltDeep;
      g.beginPath();
      g.arc(x, 560, 13, 0, TAU);
      g.fill();
      lib.inkCircle(g, x, 560, 13, { width: 2, seed: x });
    }
    if (o.poles !== false) G.drawPoles(g);
    }
  };

  G.drawPoles = (g, o = {}) => {
    for (const [x, y] of S.poles) {
      g.fillStyle = P.white;
      g.beginPath();
      g.arc(x, y, 9, 0, TAU);
      g.fill();
      lib.inkCircle(g, x, y, 9, { width: 2.4, seed: x + y });
      lib.inkLine(g, x - 5, y, x + 5, y, { width: 1.6, taper: 2, seed: x });
      lib.inkLine(g, x, y - 5, x, y + 5, { width: 1.6, taper: 2, seed: y });
    }
  };

  /** Сети на синьке: двойная линия, подпись у левого края, колодцы. */
  G.drawNetsBlue = (g, o = {}) => {
    const q = o.p != null ? o.p : 1;
    const only = o.only;
    for (const n of S.nets) {
      if (only && !only.includes(n.key)) continue;
      const pts = n.pts;
      let L = 0;
      for (let i = 0; i + 1 < pts.length; i++) L += Math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1]);
      g.save();
      g.lineCap = 'round';
      g.lineJoin = 'round';
      g.setLineDash([L * q, L * 2]);
      const off = n.channel || 0;
      const passes = off ? [-off / 2, off / 2] : [0];
      for (const d of passes) {
        g.beginPath();
        pts.forEach((p, i) => (i ? g.lineTo(p[0], p[1] + d) : g.moveTo(p[0], p[1] + d)));
        g.strokeStyle = lib.rgba(n.color, 0.25);
        g.lineWidth = 10;
        g.stroke();
        g.strokeStyle = n.color;
        g.lineWidth = 2.5;
        g.stroke();
      }
      g.restore();
      if (o.labels !== false && q > 0.2) {
        G.text(g, n.name, (o.labelX || 70), pts[0][1] - 12 - (n.channel || 0) / 2, { size: 20, weight: 500, family: G.MONO, color: n.color, alpha: 0.9 * clamp((q - 0.2) * 3), tracking: 1 });
      }
      if (n.wells) {
        for (const x of n.wells) {
          g.strokeStyle = lib.rgba(n.color, 0.8);
          g.lineWidth = 1.5;
          g.beginPath();
          g.arc(x, pts[0][1], 12 * q, 0, TAU);
          g.stroke();
        }
      }
    }
  };

  /** Контуры поверхности на синьке тонкой лавандой: здания, борта, края газонов. */
  G.drawSurfaceBlue = (g, o = {}) => {
    g.save();
    g.strokeStyle = lib.rgba(P.lavender, o.alpha != null ? o.alpha : 0.5);
    g.lineWidth = 1.5;
    for (const poly of S.buildings) {
      g.beginPath();
      lib.tracePath(g, poly, true);
      g.stroke();
    }
    g.beginPath();
    for (const y of [S.walkTop[1], S.curbA, S.curbB, S.walkB[0]]) {
      g.moveTo(-40, y);
      g.lineTo(1960, y);
    }
    g.stroke();
    g.setLineDash([4, 8]);
    g.strokeStyle = lib.rgba(P.lavender, 0.25);
    g.beginPath();
    g.moveTo(-40, 580);
    g.lineTo(1960, 580);
    g.stroke();
    g.restore();
    for (const [x, y] of S.poles) {
      g.strokeStyle = lib.rgba(P.lineWhite, 0.7);
      g.lineWidth = 1.5;
      g.beginPath();
      g.arc(x, y, 8, 0, TAU);
      g.stroke();
    }
  };

  // ---------------------------------------------------------------------------
  // Деревья и кустарники в плане
  // ---------------------------------------------------------------------------

  const crownCache = new Map();
  function crownPts(x, y, r, seed, lobes) {
    const key = [x, y, r, seed, lobes].join('|');
    let v = crownCache.get(key);
    if (v) return v;
    const rr = lib.rng(seed);
    const n = lobes || 9;
    const pts = [];
    const ph = rr() * TAU;
    const steps = n * 6;
    for (let i = 0; i < steps; i++) {
      const a = ph + (i / steps) * TAU;
      const lobe = Math.abs(Math.sin(((i % 6) / 6) * Math.PI));
      const k = 0.86 + 0.14 * lobe + 0.05 * lib.noise1(i * 0.37, seed);
      pts.push([x + Math.cos(a) * r * k, y + Math.sin(a) * r * k]);
    }
    v = pts;
    crownCache.set(key, v);
    if (crownCache.size > 3000) crownCache.clear();
    return v;
  }

  /**
   * tree(ctx, x, y, r, o) : крона сверху. o.s : масштаб появления (0..1+), o.kind 'leaf' | 'conifer',
   * o.fill / o.deep : цвета, o.hatch : штриховать тень (дорого, для крупных планов).
   */
  G.tree = (g, x, y, r, o = {}) => {
    const s = o.s != null ? o.s : 1;
    if (s <= 0.01) return;
    const seed = o.seed || Math.round(x * 7 + y * 13);
    const rad = r * s;
    const conifer = o.kind === 'conifer';
    const fill = o.fill || (conifer ? C.conifer : C.crown);
    const deep = o.deep || (conifer ? C.coniferDeep : C.crownDeep);
    let pts;
    if (conifer) {
      pts = [];
      const n = 16;
      for (let i = 0; i < n * 2; i++) {
        const a = (i / (n * 2)) * TAU;
        const k = i % 2 ? 0.62 : 1;
        pts.push([x + Math.cos(a) * rad * k, y + Math.sin(a) * rad * k]);
      }
    } else pts = crownPts(x, y, rad, seed, o.lobes);
    // тень кроны на земле
    g.save();
    g.globalAlpha *= 0.18;
    g.fillStyle = P.ink;
    g.beginPath();
    const sa = o.sun != null ? o.sun : G.sunA != null ? G.sunA : 0.9;
    const sl = o.shadow != null ? o.shadow : 0.26;
    lib.tracePath(g, pts.map(([px, py]) => [px + Math.cos(sa) * rad * sl, py + Math.sin(sa) * rad * sl]), true);
    g.fill();
    g.restore();
    // при наезде камеры дрожь линий в координатах мира растёт вместе с масштабом: гасим её
    const zb = 1 / Math.max(1, G.zoomNow || 1);
    lib.inkPath(g, pts, { closed: true, width: o.width || Math.max(1.6, Math.min(4, rad * 0.07)), fill, seed, wobble: 0.8, smooth: !conifer, boilAmp: 0.7 * zb });
    if (o.hatch !== false && rad > 14) {
      // тень на правой нижней половине
      lib.hatch(g, pts, {
        spacing: Math.max(4, rad * 0.11),
        width: Math.max(0.9, rad * 0.025),
        length: [rad * 0.2, rad * 0.55],
        color: deep,
        alpha: 0.85,
        seed: seed + 3,
        clip: true,
        density: (px, py) => clamp(((px - x) + (py - y)) / (rad * 1.2) + 0.35),
        boilAmp: 0.45 * zb,
      });
    }
    // ствол
    g.fillStyle = P.inkSoft;
    g.beginPath();
    g.arc(x, y, Math.max(1.5, rad * 0.09), 0, TAU);
    g.fill();
  };

  /** Группа кустарников: несколько мелких крон в полосе. */
  G.shrubs = (g, x, y, w, h, o = {}) => {
    const s = o.s != null ? o.s : 1;
    if (s <= 0.01) return;
    const rr = lib.rng(o.seed || Math.round(x + y * 3));
    const n = o.n || Math.max(3, Math.round((w * h) / 900));
    for (let i = 0; i < n; i++) {
      const px = x + rr() * w, py = y + rr() * h;
      const r = rr.range(9, 15);
      const q = clamp(s * 1.4 - (i / n) * 0.4);
      G.tree(g, px, py, r, { s: E.outBack(q), fill: o.fill || C.shrub, deep: C.shrubDeep, hatch: false, seed: i + 17 * (o.seed || 1), lobes: 6, width: 1.6 });
    }
  };

  // ---------------------------------------------------------------------------
  // Узел схемы на синьке: двойной круг с глифом внутри
  // ---------------------------------------------------------------------------

  G.node = (g, x, y, r, o = {}) => {
    const q = o.p != null ? o.p : 1;
    if (q <= 0) return;
    const e = E.outBack(clamp(q));
    const rr = r * e;
    g.save();
    g.fillStyle = lib.rgba(P.navyLight, 0.95);
    g.beginPath();
    g.arc(x, y, rr, 0, TAU);
    g.fill();
    g.strokeStyle = lib.rgba(P.lavender, 0.85);
    g.lineWidth = 2.5;
    g.stroke();
    g.strokeStyle = lib.rgba(P.lavender, 0.45);
    g.lineWidth = 1.5;
    g.beginPath();
    g.arc(x, y, Math.max(0, rr - 9), 0, TAU);
    g.stroke();
    if (o.lit) {
      g.strokeStyle = o.litColor || P.magenta;
      g.lineWidth = 3;
      g.beginPath();
      g.arc(x, y, rr + 8, -Math.PI / 2, -Math.PI / 2 + TAU * clamp(o.lit));
      g.stroke();
    }
    g.restore();
    if (o.glyph && q > 0.5) {
      g.save();
      g.translate(x, y);
      g.scale(e * (r / 60), e * (r / 60));
      g.globalAlpha *= clamp((q - 0.5) * 2);
      o.glyph(g);
      g.restore();
    }
  };

  /** Гибкая связь между узлами: тонкая дуга лавандой с бегущей точкой. */
  G.link = (g, x1, y1, x2, y2, o = {}) => {
    const q = o.p != null ? clamp(o.p) : 1;
    if (q <= 0) return;
    const bend = o.bend != null ? o.bend : 0.25;
    const mx = (x1 + x2) / 2 - (y2 - y1) * bend, my = (y1 + y2) / 2 + (x2 - x1) * bend;
    const pts = [];
    const n = 40;
    for (let i = 0; i <= n * q; i++) {
      const u = i / n;
      pts.push([(1 - u) * (1 - u) * x1 + 2 * (1 - u) * u * mx + u * u * x2, (1 - u) * (1 - u) * y1 + 2 * (1 - u) * u * my + u * u * y2]);
    }
    g.save();
    g.strokeStyle = lib.rgba(o.color || P.lavender, o.alpha != null ? o.alpha : 0.55);
    g.lineWidth = o.width || 1.5;
    g.beginPath();
    lib.tracePath(g, pts, false);
    g.stroke();
    g.restore();
    if (o.pulse != null && q >= 1) {
      const u = ((o.pulse % 1) + 1) % 1;
      const px = (1 - u) * (1 - u) * x1 + 2 * (1 - u) * u * mx + u * u * x2;
      const py = (1 - u) * (1 - u) * y1 + 2 * (1 - u) * u * my + u * u * y2;
      lib.glowDot(g, px, py, 4, { rays: 0, glow: 5, intensity: 0.9 });
    }
  };

  // ---------------------------------------------------------------------------
  // Кольцо внимания поверх рисунка (outExpo, 5-12 кадров)
  // ---------------------------------------------------------------------------

  G.ring = (g, x, y, r, t, t0, o = {}) => {
    const d = o.dur || 0.45;
    const q = (t - t0) / d;
    if (q <= 0 || q >= 1) return;
    const e = E.outExpo(q);
    g.save();
    g.strokeStyle = o.color || P.annYellow;
    g.globalAlpha *= 1 - q;
    g.lineWidth = o.width || 3;
    g.beginPath();
    g.arc(x, y, r * (0.6 + 0.8 * e), 0, TAU);
    g.stroke();
    g.restore();
  };

  /** Крестик отказа. */
  G.cross = (g, x, y, r, o = {}) => {
    const q = o.p != null ? clamp(o.p) : 1;
    if (q <= 0) return;
    g.save();
    g.strokeStyle = o.color || P.annMagenta;
    g.lineWidth = o.width || 3.5;
    g.lineCap = 'round';
    const a = r * E.outBack(clamp(q * 2));
    const b = r * E.outBack(clamp(q * 2 - 1));
    g.beginPath();
    g.moveTo(x - a, y - a);
    g.lineTo(x + a, y + a);
    if (b > 0) {
      g.moveTo(x + b, y - b);
      g.lineTo(x - b, y + b);
    }
    g.stroke();
    g.restore();
  };

  // ---------------------------------------------------------------------------
  // Виды из config/species.yaml (для цвета крон) и раскладка плана по улице
  // ---------------------------------------------------------------------------

  G.SPECIES = [
    { ru: 'Липа мелколистная', lat: 'Tilia cordata', h: 25, fam: 'Malvaceae', fill: '#8FAF6E', deep: '#5E8248', r: 56 },
    { ru: 'Клён остролистный', lat: 'Acer platanoides', h: 20, fam: 'Sapindaceae', fill: '#A7B85E', deep: '#707F32', r: 58 },
    { ru: 'Боярышник обыкновенный', lat: 'Crataegus laevigata', h: 6, fam: 'Rosaceae', fill: '#B9C98A', deep: '#7D9152', r: 40, thorny: true },
    { ru: 'Сосна обыкновенная', lat: 'Pinus sylvestris', h: 30, fam: 'Pinaceae', fill: '#4F7A57', deep: '#2F5A3F', r: 44, kind: 'conifer' },
    { ru: 'Вяз гладкий', lat: 'Ulmus laevis', h: 25, fam: 'Ulmaceae', fill: '#7FA37C', deep: '#4E7250', r: 54 },
    { ru: 'Рябина обыкновенная', lat: 'Sorbus aucuparia', h: 10, fam: 'Rosaceae', fill: '#C8B27A', deep: '#8E7440', r: 42 },
    { ru: 'Каштан конский обыкновенный', lat: 'Aesculus hippocastanum', h: 22, fam: 'Sapindaceae', fill: '#9DBB86', deep: '#62824E', r: 60 },
    { ru: 'Туя западная', lat: 'Thuja occidentalis', h: 6, fam: 'Cupressaceae', fill: '#5F8C6A', deep: '#3A6247', r: 34, kind: 'conifer' },
  ];
  // слои результата, src/green/infrastructure/cad/writer.py
  G.LAYERS = ['GREEN_TREES', 'GREEN_TREES_APPROVAL', 'GREEN_TREES_BARRIER', 'GREEN_SHRUBS', 'GREEN_SHRUBS_APPROVAL', 'GREEN_REJECT', 'GREEN_LABELS', 'GREEN_ZONE_ALLOWED', 'GREEN_ZONE_APPROVAL'];
  G.SHRUB_COLORS = [['#9DB77A', '#6C8F52'], ['#C3B6D9', '#8C7DAA'], ['#D9B8A0', '#A97F63'], ['#A9C7A3', '#6E9468']];
  G.ok = G.candidates.filter((c) => c.ok);
  G.rejected = G.candidates.filter((c) => !c.ok);
  // вид каждой посадки: по кругу, соседние места разного вида
  G.ok.forEach((c, k) => (c.sp = G.SPECIES[(k * 3 + (c.row === 'B' ? 1 : 0)) % G.SPECIES.length]));
  // как в сервисе (shrub_groups.py): группа кустарника встаёт только туда, где место прошло нормы,
  // но квоты разнообразия оставили его без вида дерева
  G.ok.forEach((c, k) => (c.empty = k % 4 === 2));
  G.trees = G.ok.filter((c) => !c.empty);
  // посадка №3 крупного плана: боярышник на верхнем газоне
  G.TREE3 = G.trees.find((c) => c.row === 'A' && c.x === 1260) || G.trees[0];
  G.TREE3.sp = G.SPECIES[2];
  G.shrubSpots = G.ok.filter((c) => c.empty);

  /** Деревья плана. s(k, c) : масштаб появления. o.plain : одинаковая зелень без видов; o.all : и места, пустые по квотам. */
  G.drawPlanTrees = (g, s, o = {}) => {
    G.ok.forEach((c, k) => {
      if (c.empty && !o.all) return;
      const sp = o.plain ? null : c.sp;
      const kind = sp ? sp.kind : k % 4 === 3 ? 'conifer' : 'leaf';
      const r = sp ? sp.r : kind === 'conifer' ? 44 : 54;
      G.tree(g, c.x, c.y, r, { s: s(k, c), kind, seed: c.id * 31, fill: sp && sp.fill, deep: sp && sp.deep });
    });
  };
  /** Все группы кустарников выросли: один растр вместо двухсот крон. */
  G.shrubsFull = (g) => g.drawImage(G.cachedCanvas('shrubs-full', (gg) => G.drawPlanShrubs(gg, () => 1), { boil: !((G.zoomNow || 1) > 1.15) }), 0, 0, 1920, 1080);
  /** Группы кустарников 3 x 3 с шагом 1 м на местах, пустых по квотам. */
  G.drawPlanShrubs = (g, s) => {
    G.shrubSpots.forEach((c, k) => {
      const q = s(k, c);
      if (q <= 0.01) return;
      for (let i = 0; i < 3; i++) {
        for (let j = 0; j < 3; j++) {
          const e = E.outBack(clamp(q * 1.6 - (i * 3 + j) * 0.07));
          const sh = G.SHRUB_COLORS[c.id % G.SHRUB_COLORS.length];
          G.tree(g, c.x + (i - 1) * G.M, c.y + (j - 1) * G.M, 10, { s: e, fill: sh[0], deep: sh[1], hatch: false, seed: c.id * 9 + i * 3 + j, lobes: 6, width: 1.4 });
        }
      }
    });
  };

  // ---------------------------------------------------------------------------
  // Интерфейс: графит и кость (src/green/interfaces/web/static/app.css)
  // ---------------------------------------------------------------------------

  const UI = (G.UI = {});
  UI.panel = (g, x, y, w, h, o = {}) => {
    const q = o.p != null ? o.p : 1;
    if (q <= 0) return;
    g.save();
    g.globalAlpha *= clamp(q * 1.5);
    const dy = (1 - E.outCubic(clamp(q))) * 16;
    g.fillStyle = lib.rgba(C.graphite2, 0.94);
    g.beginPath();
    g.roundRect(x, y + dy, w, h, 10);
    g.fill();
    g.strokeStyle = lib.rgba(C.bone, 0.14);
    g.lineWidth = 1.5;
    g.stroke();
    g.restore();
  };
  UI.label = (g, s, x, y, o = {}) => G.text(g, s, x, y, Object.assign({ size: 18, weight: 400, color: C.boneDim }, o));
  UI.value = (g, s, x, y, o = {}) => G.text(g, s, x, y, Object.assign({ size: 22, weight: 500, color: C.bone }, o));
  UI.field = (g, x, y, w, text, o = {}) => {
    g.save();
    g.fillStyle = o.focus ? C.graphite3 : lib.rgba(C.graphite, 0.9);
    g.beginPath();
    g.roundRect(x, y, w, 46, 6);
    g.fill();
    g.strokeStyle = lib.rgba(C.bone, o.focus ? 0.6 : 0.2);
    g.lineWidth = 1.5;
    g.stroke();
    g.restore();
    G.text(g, text, x + 16, y + 30, { size: 20, weight: 400, color: C.bone });
    if (o.select) {
      g.save();
      g.strokeStyle = C.boneDim;
      g.lineWidth = 2;
      g.beginPath();
      g.moveTo(x + w - 28, y + 19);
      g.lineTo(x + w - 20, y + 27);
      g.lineTo(x + w - 12, y + 19);
      g.stroke();
      g.restore();
    }
  };
  UI.check = (g, x, y, label, on) => {
    g.save();
    g.strokeStyle = lib.rgba(C.bone, 0.6);
    g.lineWidth = 1.5;
    g.beginPath();
    g.roundRect(x, y, 24, 24, 4);
    g.stroke();
    if (on > 0) {
      g.fillStyle = C.bone;
      g.globalAlpha *= clamp(on);
      g.beginPath();
      g.roundRect(x + 4, y + 4, 16, 16, 3);
      g.fill();
    }
    g.restore();
    G.text(g, label, x + 36, y + 19, { size: 19, weight: 400, color: C.bone });
  };
  UI.button = (g, x, y, w, h, label, o = {}) => {
    const press = o.press || 0;
    g.save();
    g.translate(x + w / 2, y + h / 2);
    g.scale(1 - press * 0.04, 1 - press * 0.04);
    g.fillStyle = o.primary ? C.bone : C.graphite3;
    g.beginPath();
    g.roundRect(-w / 2, -h / 2, w, h, 8);
    g.fill();
    if (!o.primary) {
      g.strokeStyle = lib.rgba(C.bone, 0.25);
      g.lineWidth = 1.5;
      g.stroke();
    }
    g.restore();
    G.text(g, label, x + w / 2, y + h / 2 + 7, { size: 20, weight: 600, color: o.primary ? C.graphite : C.bone, align: 'center' });
  };
  /** Курсор-стрелка. click : 0..1, кольцо нажатия. */
  UI.cursor = (g, x, y, click) => {
    if (click > 0 && click < 1) {
      g.save();
      g.strokeStyle = lib.rgba(C.signal, 1 - click);
      g.lineWidth = 2.5;
      g.beginPath();
      g.arc(x, y, 10 + 26 * E.outExpo(click), 0, TAU);
      g.stroke();
      g.restore();
    }
    g.save();
    g.translate(x, y);
    g.beginPath();
    g.moveTo(0, 0);
    g.lineTo(0, 30);
    g.lineTo(8, 23);
    g.lineTo(14, 36);
    g.lineTo(19, 34);
    g.lineTo(13, 21);
    g.lineTo(23, 21);
    g.closePath();
    g.fillStyle = C.bone;
    g.fill();
    g.strokeStyle = C.graphite;
    g.lineWidth = 2;
    g.stroke();
    g.restore();
  };
  /** Путь курсора по ключевым точкам [[t, x, y], ...] с плавными перелётами. */
  UI.path = (keys, t) => {
    if (t <= keys[0][0]) return [keys[0][1], keys[0][2]];
    for (let i = 0; i + 1 < keys.length; i++) {
      const [t0, x0, y0] = keys[i], [t1, x1, y1] = keys[i + 1];
      if (t <= t1) {
        const q = E.inOutCubic((t - t0) / (t1 - t0));
        return [lerp(x0, x1, q), lerp(y0, y1, q)];
      }
    }
    const k = keys[keys.length - 1];
    return [k[1], k[2]];
  };

  /** Улица на карте интерфейса: кость по графиту. */
  UI.street = (g, o = {}) => {
    const q = o.p != null ? o.p : 1;
    if (q <= 0) return;
    g.save();
    g.globalAlpha *= clamp(q);
    g.fillStyle = '#2A2D31';
    g.fillRect(-60, S.road[0], 2040, S.road[1] - S.road[0]);
    g.fillStyle = '#2C3A2E';
    for (const [y0, y1] of [S.lawnA, S.lawnB]) g.fillRect(-60, y0, 2040, y1 - y0);
    g.fillStyle = '#303236';
    for (const [y0, y1] of [S.walkTop, S.walkB]) g.fillRect(-60, y0, 2040, y1 - y0);
    g.restore();
    const dash = lerp(2400, 0, E.outCubic(clamp(q)));
    g.save();
    g.strokeStyle = lib.rgba(C.bone, 0.55);
    g.lineWidth = 1.5;
    g.setLineDash([2400 - dash, 2400]);
    for (const poly of S.buildings) {
      g.beginPath();
      lib.tracePath(g, poly, true);
      g.fillStyle = lib.rgba(C.bone, 0.06 * q);
      g.fill();
      g.stroke();
    }
    g.lineWidth = 2;
    g.strokeStyle = lib.rgba(C.bone, 0.7);
    for (const y of [S.curbA, S.curbB]) {
      g.beginPath();
      g.moveTo(-40, y);
      g.lineTo(1960, y);
      g.stroke();
    }
    g.lineWidth = 1;
    g.strokeStyle = lib.rgba(C.bone, 0.35);
    for (const y of [S.walkTop[1], S.walkB[0]]) {
      g.beginPath();
      g.moveTo(-40, y);
      g.lineTo(1960, y);
      g.stroke();
    }
    g.setLineDash([]);
    g.restore();
    for (const [x, y] of S.poles) {
      g.strokeStyle = lib.rgba(C.bone, 0.6 * q);
      g.lineWidth = 1.5;
      g.beginPath();
      g.arc(x, y, 7, 0, TAU);
      g.stroke();
    }
  };
  UI.nets = (g, q) => {
    if (q <= 0) return;
    g.save();
    g.globalAlpha *= q;
    for (const n of S.nets) {
      g.strokeStyle = lib.rgba(n.color, 0.85);
      g.lineWidth = 2;
      g.setLineDash([10, 6]);
      g.beginPath();
      n.pts.forEach((p, i) => (i ? g.lineTo(p[0], p[1]) : g.moveTo(p[0], p[1])));
      g.stroke();
    }
    g.restore();
  };
  UI.planting = (g, x, y, r, sp, o = {}) => {
    const s = o.s != null ? o.s : 1;
    if (s <= 0.01) return;
    g.save();
    g.fillStyle = lib.rgba(sp ? sp.fill : C.shrub, o.dim ? 0.25 : 0.8);
    g.strokeStyle = lib.rgba(C.bone, o.dim ? 0.2 : 0.8);
    g.lineWidth = 1.5;
    g.beginPath();
    g.arc(x, y, r * s, 0, TAU);
    g.fill();
    g.stroke();
    g.fillStyle = C.graphite;
    g.beginPath();
    g.arc(x, y, 3 * s, 0, TAU);
    g.fill();
    g.restore();
  };

  /** План на карте интерфейса: отклонённые места, группы кустарника, деревья. o.skip : дерево, которое рисуют отдельно. */
  UI.plan = (g, o = {}) => {
    g.save();
    g.strokeStyle = lib.rgba(C.bone, 0.35);
    g.lineWidth = 1.5;
    for (const c of G.rejected) {
      g.beginPath();
      g.arc(c.x, c.y, 9, 0, TAU);
      g.moveTo(c.x - 5, c.y - 5);
      g.lineTo(c.x + 5, c.y + 5);
      g.moveTo(c.x + 5, c.y - 5);
      g.lineTo(c.x - 5, c.y + 5);
      g.stroke();
    }
    g.restore();
    for (const c of G.shrubSpots) for (let i = -1; i <= 1; i++) for (let j = -1; j <= 1; j++) UI.planting(g, c.x + i * G.M, c.y + j * G.M, 8, null);
    for (const c of G.trees) {
      if (c === o.skip) continue;
      UI.planting(g, c.x, c.y, c.sp.r * 0.75, c.sp, { s: o.s ? o.s(c) : 1 });
    }
  };

  G.fmt = (v, d = 2) => v.toFixed(d).replace('.', ',');
  G.num = (v) => String(v).replace(/\B(?=(\d{3})+(?!\d))/g, ' ');
})();
