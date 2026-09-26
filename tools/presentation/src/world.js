/*
 * world.js : один мир для всей презентации и камера над ним.
 *
 *   карта Москвы (в пикселях карты, 1 px = 45 м) -> квартал вокруг Берзарина (растр) -> улица (20 px = 1 м).
 * Все три уровня лежат в координатах улицы; камера { x, y, z } смотрит в точку (x, y) с масштабом z
 * экранных пикселей на пиксель улицы. Перелёт между кадрами идёт по логарифму масштаба, поэтому
 * спуск с города в улицу выглядит как одно непрерывное движение.
 *
 * Здесь же: состав команды для картуша, линейка глав рассказа, лист, который отгибается как бумага,
 * и красный карандаш нормоконтроля.
 */
(function () {
  'use strict';

  const FILM = window.FILM;
  const lib = FILM.lib;
  const P = lib.pal;
  const E = lib.ease;
  const G = FILM.G;
  const C = G.C;
  const TAU = Math.PI * 2;
  const clamp = lib.clamp;
  const lerp = lib.lerp;

  // Команда: имена и роли для картуша на карте (слайд 2). Правится только здесь.
  G.TEAM = [
    { name: 'Имя Фамилия', role: 'роль в команде' },
    { name: 'Имя Фамилия', role: 'роль в команде' },
    { name: 'Имя Фамилия', role: 'роль в команде' },
    { name: 'Имя Фамилия', role: 'роль в команде' },
    { name: 'Имя Фамилия', role: 'роль в команде' },
  ];

  // ---------------------------------------------------------------------------
  // Камера
  // ---------------------------------------------------------------------------

  const K = 900; // пикселей улицы в пикселе карты: 45 м против 5 см
  const SB = [960, 560]; // где улица лежит сама на себе
  const MB = [1041, 462]; // где Берзарина лежит на карте
  G.K = K;
  G.MB = MB;
  G.CAM_STREET = { x: 960, y: 540, z: 1 };
  G.mapCam = (mx, my, m) => ({ x: SB[0] + (mx - MB[0]) * K, y: SB[1] + (my - MB[1]) * K, z: m / K });
  G.CAM_CITY = G.mapCam(1180, 560, 1);

  /** Перелёт камеры: масштаб по логарифму, центр по ширине кадра, чтобы цель не уплывала. */
  G.camLerp = (a, b, q) => {
    if (q <= 0) return a;
    if (q >= 1) return b;
    const la = Math.log(a.z), lb = Math.log(b.z);
    const z = Math.exp(lerp(la, lb, q));
    let w = q;
    if (Math.abs(lb - la) > 1e-4) w = (1 / z - 1 / a.z) / (1 / b.z - 1 / a.z);
    return { x: lerp(a.x, b.x, w), y: lerp(a.y, b.y, w), z };
  };
  /** Камера по ключам [[t, cam, easing?], ...]. */
  G.camPath = (keys, t) => {
    if (t <= keys[0][0]) return keys[0][1];
    for (let i = 0; i + 1 < keys.length; i++) {
      const [t0, c0] = keys[i], [t1, c1, e] = keys[i + 1];
      if (t <= t1) return G.camLerp(c0, c1, E[e || 'inOutCubic']((t - t0) / (t1 - t0)));
    }
    return keys[keys.length - 1][1];
  };
  G.applyCam = (ctx, cam) => {
    ctx.translate(960, 540);
    ctx.scale(cam.z, cam.z);
    ctx.translate(-cam.x, -cam.y);
  };
  G.toScreen = (cam, x, y) => [(x - cam.x) * cam.z + 960, (y - cam.y) * cam.z + 540];
  const mapToScreen = (cam, mx, my) => G.toScreen(cam, SB[0] + (mx - MB[0]) * K, SB[1] + (my - MB[1]) * K);
  G.mapToScreen = mapToScreen;

  // ---------------------------------------------------------------------------
  // Карта Москвы: стилизация, не картография
  // ---------------------------------------------------------------------------

  const CX = 1250, CY = 560; // центр города на карте
  function ring(rx, ry, seed, n = 220) {
    const out = [];
    for (let i = 0; i < n; i++) {
      const a = (i / n) * TAU;
      const k = 1 + 0.035 * lib.noise1(i * 0.09, seed) + 0.02 * lib.noise1(i * 0.31, seed + 3);
      out.push([CX + Math.cos(a) * rx * k, CY + Math.sin(a) * ry * k]);
    }
    return out;
  }
  const MAP = {
    mkad: ring(345, 385, 1),
    ttk: ring(140, 150, 2, 160),
    garden: ring(55, 58, 3, 90),
    river: lib.smoothPts([[760, 380], [880, 420], [950, 440], [990, 452], [1020, 500], [1060, 540], [1110, 560], [1150, 610], [1190, 640], [1240, 600], [1260, 560], [1300, 580], [1360, 640], [1420, 690], [1500, 760], [1640, 860]], false, 8),
    parks: [
      [1430, 300, 70, 52, 11], [1480, 530, 44, 36, 12], [1280, 860, 52, 40, 13], [985, 485, 26, 20, 14], [1340, 410, 26, 22, 15], [1060, 690, 30, 24, 16],
    ],
    radials: [],
    markers: [],
  };
  for (let k = 0; k < 11; k++) {
    const a = (k / 11) * TAU + 0.3;
    const pts = [];
    for (let s = 0; s <= 12; s++) {
      const r = 20 + s * 38;
      const aa = a + 0.06 * lib.noise1(s * 0.4, k + 20);
      pts.push([CX + Math.cos(aa) * r, CY + Math.sin(aa) * r * 1.08]);
    }
    MAP.radials.push(pts);
  }
  // второстепенные улицы, железные дороги и застройка внутри МКАД
  MAP.minor = [];
  {
    const r = lib.rng('minor');
    for (let k = 0; k < 90; k++) {
      const a = r() * TAU, d = r() * 330;
      let x = CX + Math.cos(a) * d, y = CY + Math.sin(a) * d * 1.1;
      let dir = r() * TAU;
      const pts = [[x, y]];
      const n = 3 + Math.floor(r() * 4);
      for (let i = 0; i < n; i++) {
        dir += (r() - 0.5) * 0.7;
        const L = 14 + r() * 26;
        x += Math.cos(dir) * L;
        y += Math.sin(dir) * L;
        pts.push([x, y]);
      }
      MAP.minor.push(pts);
    }
  }
  MAP.rails = [0.9, 2.3, 3.5, 5.2].map((a, k) => {
    const pts = [];
    for (let s = 0; s <= 10; s++) {
      const rad = 150 + s * 34;
      const aa = a + 0.12 * lib.noise1(s * 0.5, k + 50);
      pts.push([CX + Math.cos(aa) * rad, CY + Math.sin(aa) * rad * 1.08]);
    }
    return pts;
  });
  // 19 улиц пилота: Берзарина первой, остальные условно по городу
  MAP.markers.push(MB);
  {
    const r = lib.rng('streets');
    while (MAP.markers.length < 19) {
      const a = r() * TAU, d = 90 + r() * 250;
      const p = [CX + Math.cos(a) * d, CY + Math.sin(a) * d * 1.1];
      if (MAP.markers.every((q) => Math.hypot(q[0] - p[0], q[1] - p[1]) > 55)) MAP.markers.push(p);
    }
  }
  G.MAP = MAP;
  G.CARTOUCHE = [1530, 800, 360, 250]; // картуш с составителями, правый нижний угол листа

  const VIEW = { w: 1920, h: 1080 }; // куда рисуем: экран или растр карты
  function screenRuns(pts, margin) {
    // куски ломаной, которые попадают в кадр: остальное не рисуем
    const runs = [];
    let cur = [];
    const inView = (p) => p[0] > -margin && p[0] < VIEW.w + margin && p[1] > -margin && p[1] < VIEW.h + margin;
    for (let i = 0; i < pts.length; i++) {
      const p = pts[i];
      const prev = pts[i - 1];
      if (inView(p) || (prev && inView(prev))) {
        if (!cur.length && prev) cur.push(prev);
        cur.push(p);
      } else if (cur.length) {
        cur.push(p);
        runs.push(cur);
        cur = [];
      }
    }
    if (cur.length > 1) runs.push(cur);
    return runs;
  }

  function mapLine(ctx, cam, pts, o) {
    const rv = o.reveal != null ? o.reveal : 1;
    if (rv <= 0) return;
    const src = rv < 1 ? pts.slice(0, Math.max(2, Math.floor(pts.length * rv))) : pts;
    const sp = src.map((p) => mapToScreen(cam, p[0], p[1]));
    if (o.closed && rv >= 1) sp.push(sp[0], sp[1]);
    const m = cam.z * K;
    const calm = m > 1.3 ? { wobble: 0, tremble: 0, boilAmp: 0, widthJitter: 0.1 } : {};
    for (const run of screenRuns(sp, 80)) if (run.length > 1) lib.inkPath(ctx, run, Object.assign({}, o, calm, { closed: false, taper: o.taper || [6, 10] }));
  }

  /** Карта. o.dusk : вечерняя палитра, o.t : время для воды, облаков и меток, o.team : проявление картуша. */
  // неподвижная часть карты в растре 2x: для видов издалека, где камера плывёт медленно
  const mapRasters = {};
  function mapRaster(o, dusk) {
    const key = dusk + '|' + FILM.S.toFixed(3);
    if (mapRasters[key]) return mapRasters[key];
    const k = Math.min(2, 2 * FILM.S);
    const c = FILM.makeCanvas(Math.round(2000 * k), Math.round(1100 * k));
    const g = c.getContext('2d');
    g.scale(k, k);
    const rcam = { x: SB[0] + K * (960 - MB[0]), y: SB[1] + K * (540 - MB[1]), z: 1 / K };
    VIEW.w = 2000;
    VIEW.h = 1100;
    const saved = FILM.frameT;
    FILM.frameT = 0.001;
    mapBody(g, rcam, Object.assign({}, o, { dusk, reveal: 1 }), 'static');
    FILM.frameT = saved;
    VIEW.w = 1920;
    VIEW.h = 1080;
    mapRasters[key] = c;
    return c;
  }

  G.drawMap = (ctx, cam, o = {}) => {
    const m = cam.z * K;
    const dusk = o.dusk || 0;
    const rv = o.reveal != null ? o.reveal : 1;
    ctx.fillStyle = lib.mix('#EDE0C4', '#2B2745', dusk);
    ctx.fillRect(0, 0, 1920, 1080);
    // растр 2x до m = 8, выше вектор; в полосе 6..8 они растворяются друг в друге
    const rasterOK = rv >= 1 && (dusk === 0 || dusk === 1);
    const ra = rasterOK ? 1 - clamp((m - 6) / 2) : 0;
    if (ra < 1) mapBody(ctx, cam, o, 'static');
    if (ra > 0) {
      const [sx, sy] = mapToScreen(cam, 0, 0);
      ctx.save();
      ctx.globalAlpha *= ra;
      ctx.drawImage(mapRaster(o, dusk), sx, sy, 2000 * m, 1100 * m);
      ctx.restore();
    }
    mapBody(ctx, cam, o, 'live');
  };

  function mapBody(ctx, cam, o, part) {
    const ST = part === 'static', LV = part === 'live';
    const m = cam.z * K;
    const t = o.t || 0;
    const dusk = o.dusk || 0;
    const rv = o.reveal != null ? o.reveal : 1;
    const rvA = (a, b) => clamp((rv - a) / (b - a));
    const ink = lib.mix(P.ink, '#E9E1F5', dusk * 0.85);
    const paperCol = lib.mix('#EDE0C4', '#2B2745', dusk);
    if (ST) {
    // градусная сетка: линии листа, по ним видно движение камеры
    ctx.save();
    ctx.strokeStyle = lib.rgba(dusk ? '#8C83B8' : P.inkFaint, 0.18);
    ctx.lineWidth = 1;
    ctx.beginPath();
    const step = 100;
    const x0 = MB[0] + (cam.x - SB[0]) / K - 960 / m, y0 = MB[1] + (cam.y - SB[1]) / K - 540 / m;
    for (let gx = Math.floor((x0 - 200) / step) * step; gx < x0 + VIEW.w / m + 200; gx += step) {
      const [sx] = mapToScreen(cam, gx, 0);
      ctx.moveTo(sx, 0);
      ctx.lineTo(sx, VIEW.h);
    }
    for (let gy = Math.floor((y0 - 200) / step) * step; gy < y0 + VIEW.h / m + 200; gy += step) {
      const [, sy] = mapToScreen(cam, 0, gy);
      ctx.moveTo(0, sy);
      ctx.lineTo(VIEW.w, sy);
    }
    ctx.stroke();
    ctx.restore();
    // застройка внутри МКАД чуть темнее листа
    if (rvA(0.5, 0.9) > 0) {
      const poly = MAP.mkad.map((p) => mapToScreen(cam, p[0], p[1]));
      ctx.save();
      ctx.globalAlpha *= rvA(0.5, 0.9);
      ctx.fillStyle = lib.mix(paperCol, dusk ? '#1E1B33' : '#D8C6A2', 0.45);
      ctx.beginPath();
      lib.tracePath(ctx, poly, true);
      ctx.fill();
      ctx.restore();
      MAP.minor.forEach((pts, k) => mapLine(ctx, cam, pts, { width: 1, color: ink, alpha: 0.3 * rvA(0.5, 0.9), seed: 500 + k, wobble: 0.4, taper: [2, 4] }));
    }
    // парки: заливка и штриховка
    for (const [px, py, rx, ry, seed] of MAP.parks) {
      if (rvA(0.5, 0.9) <= 0) break;
      const pts = lib.ellipsePts(px, py, rx, ry, 40).map(([x, y], i) => {
        const k = 1 + 0.12 * lib.noise1(i * 0.5, seed);
        return mapToScreen(cam, px + (x - px) * k, py + (y - py) * k);
      });
      if (m < 4) lib.inkPath(ctx, pts, { closed: true, width: 2, fill: lib.mix(dusk ? '#3F4D46' : '#C7D2AE', paperCol, 0.1), color: ink, seed, wobble: 1 });
      else {
        // вблизи контур парка простой: тысячи точек пера на экране не видны
        ctx.beginPath();
        lib.tracePath(ctx, pts, true);
        ctx.fillStyle = lib.mix(dusk ? '#3F4D46' : '#C7D2AE', paperCol, 0.1);
        ctx.fill();
        ctx.strokeStyle = ink;
        ctx.lineWidth = 2;
        ctx.stroke();
      }
      // крапинки в координатах карты: при полёте камеры они едут вместе с листом, а не переигрываются
      {
        const [ox, oy] = mapToScreen(cam, 0, 0);
        ctx.save();
        ctx.translate(ox, oy);
        ctx.scale(m, m);
        const mp = lib.ellipsePts(px, py, rx, ry, 40).map(([x, y], i) => {
          const k = 1 + 0.12 * lib.noise1(i * 0.5, seed);
          return [px + (x - px) * k, py + (y - py) * k];
        });
        // вблизи крапинок становится слишком много, парк остаётся заливкой
        if (m < 4) lib.stipple(ctx, mp, { spacing: 9 / Math.sqrt(m), r: [1 / m, 2 / m], color: lib.mix('#6E8F4F', ink, 0.2), alpha: 0.5, seed, boil: m > 1.3 ? false : undefined });
        ctx.restore();
      }
    }
    // река: лента с течением
    const rs = MAP.river.slice(0, Math.max(2, Math.floor(MAP.river.length * rvA(0.1, 0.7)))).map((p) => mapToScreen(cam, p[0], p[1]));
    const rw = Math.max(6, 11 * m);
    ctx.save();
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';
    ctx.strokeStyle = dusk ? '#3E5B7A' : '#9CC6CF';
    ctx.lineWidth = rw;
    ctx.beginPath();
    lib.tracePath(ctx, rs, false);
    ctx.stroke();
    ctx.restore();
    }
    if (LV) {
    const rs = MAP.river.slice(0, Math.max(2, Math.floor(MAP.river.length * rvA(0.1, 0.7)))).map((p) => mapToScreen(cam, p[0], p[1]));
    const rw = Math.max(6, 11 * m);
    ctx.save();
    ctx.lineCap = 'round';
    ctx.beginPath();
    lib.tracePath(ctx, rs, false);
    ctx.strokeStyle = lib.rgba(dusk ? '#9CC2EA' : P.white, 0.8);
    ctx.lineWidth = Math.max(1.2, rw * 0.12);
    ctx.setLineDash([rw * 1.4, rw * 1.6]);
    ctx.lineDashOffset = -t * 40 * Math.max(1, m * 0.4);
    ctx.stroke();
    ctx.restore();
    }
    if (ST) {
    mapLine(ctx, cam, MAP.river.map(([x, y]) => [x, y - 5.5]), { width: 1.6, color: ink, seed: 71, wobble: 0.8, reveal: rvA(0.1, 0.7) });
    mapLine(ctx, cam, MAP.river.map(([x, y]) => [x, y + 5.5]), { width: 1.6, color: ink, seed: 72, wobble: 0.8, reveal: rvA(0.1, 0.7) });
    // вылетные магистрали и кольца
    MAP.radials.forEach((pts, k) => mapLine(ctx, cam, pts, { width: 1.4, color: ink, alpha: 0.45, seed: 80 + k, wobble: 0.6, reveal: rvA(0.3, 0.9) }));
    MAP.rails.forEach((pts, k) => {
      const q = rvA(0.6, 1);
      if (q <= 0) return;
      mapLine(ctx, cam, pts, { width: 1.6, color: ink, alpha: 0.7, seed: 600 + k, wobble: 0.3, reveal: q });
      // шпалы
      const sp = pts.map((p) => mapToScreen(cam, p[0], p[1]));
      ctx.save();
      ctx.strokeStyle = lib.rgba(ink, 0.6);
      ctx.lineWidth = 1.2;
      ctx.beginPath();
      for (let i = 0; i + 1 < sp.length * q - 1; i++) {
        const [x0, y0] = sp[i], [x1, y1] = sp[i + 1];
        const L = Math.hypot(x1 - x0, y1 - y0) || 1;
        const nx = -(y1 - y0) / L, ny = (x1 - x0) / L;
        for (let u = 0; u < 1; u += (8 * m) / L) {
          const x = x0 + (x1 - x0) * u, y = y0 + (y1 - y0) * u;
          ctx.moveTo(x - nx * 4, y - ny * 4);
          ctx.lineTo(x + nx * 4, y + ny * 4);
        }
      }
      ctx.stroke();
      ctx.restore();
    });
    mapLine(ctx, cam, MAP.garden, { closed: true, width: 2.4, color: ink, seed: 3, wobble: 0.8, reveal: rvA(0.4, 0.8) });
    mapLine(ctx, cam, MAP.ttk, { closed: true, width: 3, color: ink, seed: 2, wobble: 0.9, reveal: rvA(0.2, 0.7) });
    mapLine(ctx, cam, MAP.mkad, { closed: true, width: 4.2, color: ink, seed: 1, wobble: 1, double: rv >= 1, reveal: rvA(0, 0.6) });
    // Кремль
    const kr = [[CX - 6, CY + 4], [CX + 7, CY + 5], [CX + 1, CY - 7]].map((p) => mapToScreen(cam, p[0], p[1]));
    lib.inkPath(ctx, kr, { closed: true, width: 2, fill: dusk ? '#C8C1EF' : '#C88C86', color: ink, seed: 9, smooth: false });
    if (m < 3) {
      const lab = (s, mx, my) => {
        const [sx, sy] = mapToScreen(cam, mx, my);
        G.text(ctx, s, sx, sy, { size: 15, weight: 500, family: G.MONO, color: ink, alpha: 0.55, tracking: 3 });
      };
      lab('МКАД', CX + 250, CY - 300);
      lab('ТТК', CX + 96, CY - 118);
      lab('МОСКВА-РЕКА', 1330, 668);
    }
    {
      const [bx, by] = mapToScreen(cam, 1560, 760);
      const [bx2] = mapToScreen(cam, 1560 + 111, 760);
      if (bx2 - bx < 900) {
        lib.ticks(ctx, bx, by, { length: bx2 - bx, n: 5, len: 8, major: 5, majorLen: 14, color: ink, alpha: 0.7, width: 1.6 });
        G.text(ctx, '5 км', bx2 + 10, by + 6, { size: 16, weight: 500, family: G.MONO, color: ink, alpha: 0.7 });
      }
    }
    return;
    }
    // тени облаков плывут по листу; вблизи их не видно, пропускаем
    ctx.save();
    for (let k = 0; k < (m < 3 ? 5 : 0); k++) {
      const r = lib.rng('cloud' + k);
      const mx = ((r() * 2400 + t * (14 + k * 3)) % 2600) - 400, my = 150 + r() * 800;
      const [sx, sy] = mapToScreen(cam, mx, my);
      const rad = (140 + r() * 120) * m;
      if (sx < -rad || sx > 1920 + rad || sy < -rad || sy > 1080 + rad) continue;
      const g = ctx.createRadialGradient(sx, sy, 0, sx, sy, rad);
      g.addColorStop(0, lib.rgba(dusk ? '#000' : P.ink, dusk ? 0.12 : 0.06));
      g.addColorStop(1, lib.rgba(P.ink, 0));
      ctx.fillStyle = g;
      ctx.fillRect(sx - rad, sy - rad, rad * 2, rad * 2);
    }
    ctx.restore();
    // метки улиц пилота
    MAP.markers.forEach(([mx, my], k) => {
      const [sx, sy] = mapToScreen(cam, mx, my);
      if (sx < -40 || sx > 1960 || sy < -40 || sy > 1120) return;
      const bloom = o.bloom != null ? clamp(o.bloom * 19 - k) : 0;
      const pop = E.outBack(clamp(rvA(0.75, 1) * 19 - k * 0.6));
      if (pop <= 0) return;
      const hot = k === 0;
      const r = (hot ? 7 : 5) * Math.min(3, Math.max(1, m * 0.6)) * pop;
      if (dusk) {
        lib.glowDot(ctx, sx, sy, r * (0.6 + 0.8 * bloom), { color: '#D9F26B', rays: bloom > 0.5 ? 8 : 0, intensity: 0.4 + 0.8 * bloom, seed: k });
      } else {
        ctx.fillStyle = hot ? P.annMagenta : lib.rgba(P.teal, 0.9);
        ctx.beginPath();
        ctx.arc(sx, sy, r, 0, TAU);
        ctx.fill();
        lib.inkCircle(ctx, sx, sy, r + 3, { width: 1.6, color: ink, seed: k + 40 });
      }
      if (hot && !dusk) {
        const ph = (t * 0.8) % 1;
        ctx.save();
        ctx.strokeStyle = lib.rgba(P.annMagenta, 1 - ph);
        ctx.lineWidth = 2.5;
        ctx.beginPath();
        ctx.arc(sx, sy, r + 6 + ph * 30, 0, TAU);
        ctx.stroke();
        ctx.restore();
      }
    });
    // роза ветров и масштаб
    {
      const [sx, sy] = mapToScreen(cam, 1790, 150);
      const R = 48 * m;
      if (R < 400) {
        const rot = t * 0.05;
        for (let k = 0; k < 8; k++) {
          const a = rot + (k * TAU) / 8 - Math.PI / 2;
          const L = k % 2 ? R * 0.5 : R;
          lib.inkPath(ctx, [[sx, sy], [sx + Math.cos(a) * L, sy + Math.sin(a) * L]], { width: k === 0 ? 3 : 1.6, color: k === 0 ? P.annMagenta : ink, seed: 90 + k, taper: 3 });
        }
        lib.inkCircle(ctx, sx, sy, R * 0.72, { width: 1.4, color: ink, seed: 99, alpha: 0.6 });
        G.text(ctx, 'С', sx + Math.cos(rot - Math.PI / 2) * (R + 16), sy + Math.sin(rot - Math.PI / 2) * (R + 16) + 6, { size: 18, weight: 600, family: G.MONO, color: ink, align: 'center' });
      }
    }
    drawCartouche(ctx, cam, t, o.team || 0, ink, dusk);
  }

  function drawCartouche(ctx, cam, t, reveal, ink, dusk) {
    const [cx, cy, cw, ch] = G.CARTOUCHE;
    const [sx, sy] = mapToScreen(cam, cx, cy);
    const [ex, ey] = mapToScreen(cam, cx + cw, cy + ch);
    const w = ex - sx, h = ey - sy;
    if (sx > 1960 || sy > 1120 || ex < -40 || ey < -40) return;
    const s = w / cw; // экранных пикселей на пиксель картуша
    ctx.save();
    ctx.fillStyle = lib.rgba(dusk ? '#353052' : '#F4EAD3', 0.95);
    ctx.fillRect(sx, sy, w, h);
    ctx.restore();
    lib.inkPath(ctx, lib.rectPts(sx, sy, w, h, 30), { closed: true, width: Math.max(1.5, 1.2 * s), color: ink, seed: 301, smooth: false, wobble: 0.8 });
    lib.inkPath(ctx, lib.rectPts(sx + 6 * s, sy + 6 * s, w - 12 * s, h - 12 * s, 30), { closed: true, width: Math.max(1, 0.6 * s), color: ink, alpha: 0.7, seed: 302, smooth: false, wobble: 0.8 });
    // завитки по углам растут вместе с проявлением
    const grow = clamp(reveal * 1.4);
    for (const [kx, ky, dx, dy, ks] of [[sx, sy, 1, 1, 0], [ex, sy, -1, 1, 1], [sx, ey, 1, -1, 2], [ex, ey, -1, -1, 3]]) {
      if (grow <= 0) break;
      const pts = [];
      for (let i = 0; i <= 24 * grow; i++) {
        const a = (i / 24) * TAU * 1.1;
        const r = (22 - i * 0.7) * s;
        pts.push([kx + dx * (16 * s + Math.cos(a) * r * 0.6), ky + dy * (16 * s + Math.sin(a) * r * 0.6)]);
      }
      if (pts.length > 1) lib.inkPath(ctx, pts, { width: Math.max(1, 0.7 * s), color: ink, seed: 320 + ks, taper: [2, 8] });
    }
    // пока имён нет, строки обозначены штрихами; они гаснут, когда вписывается первое имя
    const ph = 1 - clamp(reveal * 4);
    if (ph > 0) for (let i = 0; i < 6; i++) lib.inkLine(ctx, sx + 30 * s, sy + (60 + i * 30) * s, sx + (cw - 60 - (i % 2) * 60) * s, sy + (60 + i * 30) * s, { width: Math.max(1, 0.5 * s), color: ink, alpha: 0.4 * ph, seed: 310 + i });
    if (reveal <= 0) return;
    G.text(ctx, 'КОМАНДА', sx + w / 2, sy + 44 * s, { size: 13 * s, weight: 600, family: G.MONO, color: ink, align: 'center', tracking: 3 * s, p: clamp(reveal * 3) });
    lib.ticks(ctx, sx + w / 2 - 70 * s, sy + 54 * s, { length: 140 * s * clamp(reveal * 3), n: 14, len: 3 * s, major: 7, majorLen: 6 * s, color: ink, alpha: 0.5, width: Math.max(1, 0.5 * s) });
    G.TEAM.forEach((p, i) => {
      const q = clamp(reveal * 7 - 1.4 - i * 0.9);
      const y = sy + (84 + i * 32) * s;
      if (q <= 0) return;
      // значок: крона вида из каталога
      const sp = G.SPECIES[(i * 3) % G.SPECIES.length];
      G.tree(ctx, sx + 30 * s, y - 5 * s, 10 * s, { s: E.outBack(clamp(q * 2)), kind: sp.kind, fill: sp.fill, deep: sp.deep, hatch: s > 2, seed: 400 + i, width: Math.max(1, 0.5 * s) });
      G.text(ctx, p.name, sx + 52 * s, y, { size: 14 * s, weight: 500, color: ink, p: q });
      G.text(ctx, p.role, sx + cw * s - 40 * s, y, { size: 10.5 * s, weight: 400, color: dusk ? '#C8C1EF' : P.inkSoft, align: 'right', p: q });
    });
  }

  // ---------------------------------------------------------------------------
  // Квартал вокруг Берзарина: векторные фигуры в координатах улицы, рисуются с отсечением
  // ---------------------------------------------------------------------------

  const DIST = { x: SB[0] - 36000, y: SB[1] - 20250, w: 72000, h: 40500 };
  const HOLE = [-60, -60, 1980, 1140]; // здесь лежит сама улица, квартал её не перекрывает
  let distShapes = null;
  function districtShapes() {
    if (distShapes) return distShapes;
    const S = G.street;
    const out = { bands: [], rects: [], dots: [] };
    const band = (x, y, w, h, fill) => out.bands.push([x, y, w, h, fill]);
    const hs = [-8500, -16500, 9200, 16800];
    const vs = [-31000, -22500, -13000, -4200, 6400, 15200, 24800, 33000];
    band(DIST.x, S.walkTop[0], DIST.w, S.walkB[1] - S.walkTop[0], C.tile);
    band(DIST.x, S.lawnA[0], DIST.w, S.lawnA[1] - S.lawnA[0], C.lawn);
    band(DIST.x, S.lawnB[0], DIST.w, S.lawnB[1] - S.lawnB[0], C.lawn);
    band(DIST.x, S.road[0], DIST.w, S.road[1] - S.road[0], C.asphalt);
    for (const y of hs) {
      band(DIST.x, y - 300, DIST.w, 600, C.tile);
      band(DIST.x, y - 180, DIST.w, 360, C.asphalt);
    }
    for (const x of vs) {
      band(x - 280, DIST.y, 560, DIST.h, C.tile);
      band(x - 170, DIST.y, 340, DIST.h, C.asphalt);
    }
    const r = lib.rng('district');
    const inHole = (x0, y0, x1, y1) => x1 > HOLE[0] && x0 < HOLE[2] && y1 > HOLE[1] && y0 < HOLE[3];
    const ys = [DIST.y, -16500, -8500, S.road[0] - 1, S.road[1] + 1, 9200, 16800, DIST.y + DIST.h].sort((a, b) => a - b);
    const xs = [DIST.x, ...vs, DIST.x + DIST.w].sort((a, b) => a - b);
    for (let i = 0; i + 1 < ys.length; i++) {
      for (let j = 0; j + 1 < xs.length; j++) {
        const bx0 = xs[j] + 400, bx1 = xs[j + 1] - 400;
        let by0 = ys[i] + 400, by1 = ys[i + 1] - 400;
        if (Math.abs(ys[i] - (S.road[1] + 1)) < 2) by0 = S.facadeBot;
        if (Math.abs(ys[i + 1] - (S.road[0] - 1)) < 2) by1 = S.facadeTop;
        if (by1 - by0 < 600 || bx1 - bx0 < 800) continue;
        let y = by0;
        while (y < by1 - 400) {
          const hgt = 400 + r() * 900;
          let x = bx0;
          while (x < bx1 - 500) {
            const wid = 700 + r() * 2200;
            const x1 = Math.min(bx1, x + wid), y1 = Math.min(by1, y + hgt);
            if (!inHole(x, y, x1, y1)) {
              if (r() < 0.76) out.rects.push([x, y, x1 - x, y1 - y, r() < 0.5 ? C.roof : '#DCC9A6']);
              else for (let k = 0; k < 5; k++) out.dots.push([x + r() * wid, y + r() * hgt, 60 + r() * 90, r() < 0.5 ? C.crown : C.crownDeep]);
            }
            x += wid + 200 + r() * 300;
          }
          y += hgt + 300 + r() * 400;
        }
      }
    }
    // деревья вдоль соседних улиц и продолжение аллеи главной
    for (const y of hs) for (let x = DIST.x; x < DIST.x + DIST.w; x += 150 + r() * 80) {
      out.dots.push([x, y - 240, 55, C.crownDeep]);
      out.dots.push([x + 60, y + 240, 55, C.crownDeep]);
    }
    for (let x = DIST.x; x < DIST.x + DIST.w; x += 120) {
      if (x > HOLE[0] - 60 && x < HOLE[2] + 60) continue;
      out.dots.push([x, 410, 50, C.crown]);
      out.dots.push([x + 60, 740, 50, C.crown]);
    }
    out.river = MAP.river.map(([mx, my]) => [SB[0] + (mx - MB[0]) * K, SB[1] + (my - MB[1]) * K]);
    distShapes = out;
    return out;
  }

  function drawDistrict(ctx, cam, alpha) {
    const D = districtShapes();
    const vx0 = cam.x - 980 / cam.z, vx1 = cam.x + 980 / cam.z, vy0 = cam.y - 560 / cam.z, vy1 = cam.y + 560 / cam.z;
    const vis = (x, y, w, h) => x + w > vx0 && x < vx1 && y + h > vy0 && y < vy1;
    ctx.save();
    ctx.globalAlpha *= alpha;
    G.applyCam(ctx, cam);
    ctx.fillStyle = '#EDE0C4';
    ctx.fillRect(Math.max(DIST.x, vx0), Math.max(DIST.y, vy0), Math.min(DIST.x + DIST.w, vx1) - Math.max(DIST.x, vx0), Math.min(DIST.y + DIST.h, vy1) - Math.max(DIST.y, vy0));
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';
    ctx.strokeStyle = '#9CC6CF';
    ctx.lineWidth = 11 * K;
    ctx.beginPath();
    lib.tracePath(ctx, D.river, false);
    ctx.stroke();
    for (const [x, y, w, h, f] of D.bands) {
      if (!vis(x, y, w, h)) continue;
      ctx.fillStyle = f;
      ctx.fillRect(x, y, w, h);
    }
    const byFill = new Map();
    const strokes = new Path2D();
    for (const [x, y, w, h, f] of D.rects) {
      if (!vis(x, y, w, h)) continue;
      let p = byFill.get(f);
      if (!p) byFill.set(f, (p = new Path2D()));
      p.rect(x, y, w, h);
      strokes.rect(x, y, w, h);
    }
    for (const [f, p] of byFill) {
      ctx.fillStyle = f;
      ctx.fill(p);
    }
    // уровни детализации: контуры и деревья дворов рисуются, только когда их видно
    // контуры и точки дворов проявляются по масштабу, а не включаются разом
    const la = clamp((cam.z - 0.008) / 0.008);
    if (la > 0) {
      ctx.strokeStyle = lib.rgba(P.ink, 0.8 * la);
      ctx.lineWidth = 1.4 / cam.z;
      ctx.stroke(strokes);
    }
    const da = clamp((cam.z * 60 - 1.5) / 1.5);
    if (da <= 0) {
      ctx.restore();
      return;
    }
    ctx.globalAlpha *= da;
    const dotFill = new Map();
    for (const [x, y, r, f] of D.dots) {
      if (!vis(x - r, y - r, r * 2, r * 2)) continue;
      let p = dotFill.get(f);
      if (!p) dotFill.set(f, (p = new Path2D()));
      p.moveTo(x + r, y);
      p.arc(x, y, r, 0, TAU);
    }
    for (const [f, p] of dotFill) {
      ctx.fillStyle = f;
      ctx.fill(p);
      if (cam.z > 0.1) {
        ctx.strokeStyle = lib.rgba(P.ink, 0.5);
        ctx.lineWidth = 1 / cam.z;
        ctx.stroke(p);
      }
    }
    ctx.restore();
  }

  // ---------------------------------------------------------------------------
  // Мир целиком под камерой
  // ---------------------------------------------------------------------------

  /** Растр улицы с мягкими краями: для вида издалека. */
  function feathered() {
    return G.cachedCanvas('surfaceFeather', (g) => {
      g.fillStyle = P.paper;
      g.fillRect(0, 0, 1920, 1080);
      G.drawSurface(g);
      // маска: единица внутри, к краям плавно в ноль; destination-in одним кадром
      const mask = FILM.makeCanvas(480, 270);
      const mg = mask.getContext('2d');
      mg.fillStyle = '#000';
      mg.fillRect(0, 0, 480, 270);
      mg.globalCompositeOperation = 'destination-out';
      const f = 26;
      const strip = (x0, y0, x1, y1, rx, ry, rw, rh) => {
        const gr = mg.createLinearGradient(x0, y0, x1, y1);
        gr.addColorStop(0, 'rgba(0,0,0,1)');
        gr.addColorStop(1, 'rgba(0,0,0,0)');
        mg.fillStyle = gr;
        mg.fillRect(rx, ry, rw, rh);
      };
      strip(0, 0, f, 0, 0, 0, f, 270);
      strip(480, 0, 480 - f, 0, 480 - f, 0, f, 270);
      strip(0, 0, 0, f, 0, 0, 480, f);
      strip(0, 270, 0, 270 - f, 0, 270 - f, 480, f);
      g.globalCompositeOperation = 'destination-in';
      g.drawImage(mask, 0, 0, 1920, 1080);
      g.globalCompositeOperation = 'source-over';
    });
  }

  /**
   * world(ctx, cam, o) : карта, квартал и улица под камерой, с переходами по масштабу.
   * o.t : время; o.dusk : вечер; o.team : картуш; o.street : рисовать ли улицу (по умолчанию да);
   * o.plan(ctx) : что нарисовать поверх улицы в её координатах (посадки и пометки).
   */
  G.world = (ctx, cam, o = {}) => {
    const m = cam.z * K;
    // карту не рисуем, когда квартал целиком закрывает кадр
    const vw = 960 / cam.z, vh = 540 / cam.z;
    const covered = m > 12 && cam.x - vw > DIST.x && cam.x + vw < DIST.x + DIST.w && cam.y - vh > DIST.y && cam.y + vh < DIST.y + DIST.h;
    const mapA = covered ? 0 : 1 - clamp((m - 14) / 26);
    if (mapA > 0) {
      // карта проявляется по мере подъёма камеры, а не включается разом
      ctx.save();
      ctx.globalAlpha *= mapA;
      G.drawMap(ctx, cam, o);
      ctx.restore();
    }
    const distA = clamp((m - 5) / 7) * (o.district === false ? 0 : 1);
    if (distA > 0 && cam.z < 1.6) {
      drawDistrict(ctx, cam, distA);
      // вечерняя накладка только на квартал: карта темнеет своей палитрой
      if (o.tint) {
        ctx.save();
        ctx.globalAlpha *= distA;
        G.applyCam(ctx, cam);
        ctx.fillStyle = lib.rgba('#2B2745', 0.62 * o.tint);
        ctx.fillRect(DIST.x, DIST.y, DIST.w, DIST.h);
        ctx.restore();
      }
    }
    const strA = clamp((cam.z - 1 / 45) / (1 / 45)) * (o.street === false ? 0 : 1);
    if (strA > 0) {
      ctx.save();
      ctx.globalAlpha *= strA;
      G.applyCam(ctx, cam);
      // издалека края улицы растворяются в квартале; у самого плана растр полный, переход плавный
      const full = clamp((cam.z - 0.86) / 0.12);
      if (full < 1) ctx.drawImage(feathered(), 0, 0, 1920, 1080);
      if (full > 0) {
        ctx.save();
        ctx.globalAlpha *= full;
        ctx.fillStyle = P.paper;
        ctx.fillRect(0, 0, 1920, 1080);
        G.cached(ctx, 'surface', (g) => G.drawSurface(g), { boil: cam.z < 1.15 });
        ctx.restore();
      }
      if (o.plan) o.plan(ctx);
      if (o.tint) {
        ctx.fillStyle = lib.rgba('#2B2745', 0.62 * o.tint);
        ctx.fillRect(-100, -100, 2120, 1280);
      }
      ctx.restore();
    }
  };

  // ---------------------------------------------------------------------------
  // Линейка глав: нить рассказа вверху кадра
  // ---------------------------------------------------------------------------

  G.CHAPTERS = ['чтение', 'нормы', 'размещение', 'виды', 'объяснение', 'качество', 'сверка'];
  G.chapters = (ctx, t, cur, o = {}) => {
    const blue = o.blue;
    const col = blue ? P.lavender : o.color || P.inkSoft;
    const hot = blue ? P.magenta : P.annMagenta;
    const x0 = 1040, x1 = 1860, y = 52;
    const n = G.CHAPTERS.length;
    const seg = (x1 - x0) / n;
    const a = (o.fadeIn ? G.seg(t, 0.1, 0.5, 'linear') : 1) * (o.alpha != null ? o.alpha : 1);
    if (a <= 0) return;
    ctx.save();
    ctx.globalAlpha *= a;
    ctx.fillStyle = blue ? lib.rgba(P.navyLight, 0.9) : lib.rgba(P.paper, 0.92);
    ctx.fillRect(x0 - 30, y - 30, x1 - x0 + 60, 82);
    ctx.strokeStyle = lib.rgba(col, 0.5);
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.moveTo(x0, y);
    ctx.lineTo(x1, y);
    for (let k = 0; k <= n; k++) {
      ctx.moveTo(x0 + k * seg, y - 6);
      ctx.lineTo(x0 + k * seg, y + 6);
    }
    ctx.stroke();
    // пройденное и текущая глава
    ctx.strokeStyle = hot;
    ctx.lineWidth = 3.5;
    ctx.beginPath();
    ctx.moveTo(x0, y);
    ctx.lineTo(x0 + (cur + G.seg(t, 0.4, o.dur ? o.dur - 1 : 8, 'linear')) * seg, y);
    ctx.stroke();
    ctx.restore();
    G.CHAPTERS.forEach((s, k) => {
      G.text(ctx, s, x0 + k * seg + seg / 2, y + 28, {
        size: 15, weight: k === cur ? 700 : 500, family: G.MONO, color: k === cur ? (blue ? P.lineWhite : P.ink) : col,
        align: 'center', alpha: a * (k <= cur ? 1 : 0.55),
      });
    });
  };

  // ---------------------------------------------------------------------------
  // Лист отгибается от угла: под бумагой синька
  // ---------------------------------------------------------------------------

  function clipHalf(poly, px, py, nx, ny, keepPositive) {
    // Сазерленд-Ходжман по одной прямой: оставляем точки, где (p - P)·n >= 0 (или <= 0)
    const out = [];
    const side = (p) => ((p[0] - px) * nx + (p[1] - py) * ny) * (keepPositive ? 1 : -1);
    for (let i = 0; i < poly.length; i++) {
      const a = poly[i], b = poly[(i + 1) % poly.length];
      const sa = side(a), sb = side(b);
      if (sa >= 0) out.push(a);
      if (sa >= 0 !== sb >= 0) {
        const u = sa / (sa - sb);
        out.push([a[0] + (b[0] - a[0]) * u, a[1] + (b[1] - a[1]) * u]);
      }
    }
    return out;
  }

  /**
   * peel(ctx, q, under, over) : лист over отгибается от правого нижнего угла, открывая under.
   * q = 0 лист лежит, q = 1 лист убран целиком.
   */
  G.peel = (ctx, q, under, over) => {
    if (q <= 0.001) { over(ctx); return; }
    under(ctx);
    if (q >= 0.999) return;
    const d = [-0.84, -0.54]; // куда движется линия сгиба
    const L = 1920 * 0.84 + 1080 * 0.54 + 60;
    const e = E.inOutCubic(q);
    const fx = 1920 + d[0] * L * e, fy = 1080 + d[1] * L * e;
    const frame = [[0, 0], [1920, 0], [1920, 1080], [0, 1080]];
    const rest = clipHalf(frame, fx, fy, -d[0], -d[1], false); // сторона, где лист ещё лежит
    const lifted = clipHalf(frame, fx, fy, -d[0], -d[1], true);
    ctx.save();
    ctx.beginPath();
    lib.tracePath(ctx, rest, true);
    ctx.clip();
    over(ctx);
    ctx.restore();
    if (lifted.length < 3) return;
    // отражение поднятой части через линию сгиба: изнанка листа
    const refl = lifted.map(([x, y]) => {
      const s = (x - fx) * d[0] + (y - fy) * d[1];
      return [x - 2 * s * d[0], y - 2 * s * d[1]];
    });
    ctx.save();
    ctx.fillStyle = 'rgba(0,0,0,0.18)';
    ctx.beginPath();
    lib.tracePath(ctx, refl.map(([x, y]) => [x + 14, y + 18]), true);
    ctx.fill();
    const gr = ctx.createLinearGradient(fx, fy, fx + d[0] * 300, fy + d[1] * 300);
    gr.addColorStop(0, '#D9C8A6');
    gr.addColorStop(0.35, '#F3E9D2');
    gr.addColorStop(1, '#E6D6B5');
    ctx.fillStyle = gr;
    ctx.beginPath();
    lib.tracePath(ctx, refl, true);
    ctx.fill();
    ctx.restore();
    lib.hatch(ctx, refl, { angle: Math.atan2(d[1], d[0]) + Math.PI / 2, spacing: 9, width: 1.2, color: P.inkSoft, alpha: 0.35, clip: true, density: (x, y) => 1 - clamp(((x - fx) * d[0] + (y - fy) * d[1]) / 120) });
    lib.inkPath(ctx, refl, { closed: true, width: 2.4, seed: 61, smooth: false, wobble: 0.6 });
  };

  // ---------------------------------------------------------------------------
  // Красный карандаш: обвод нарушения от руки
  // ---------------------------------------------------------------------------

  G.scribble = (ctx, x, y, r, q, seed, o = {}) => {
    if (q <= 0) return;
    const rr = lib.rng(seed);
    const turns = 1.25 + rr() * 0.3;
    const n = Math.max(2, Math.floor(60 * clamp(q)));
    const pts = [];
    const a0 = rr() * TAU;
    for (let i = 0; i <= n; i++) {
      const u = i / 60;
      const a = a0 + u * TAU * turns;
      const k = 1 + 0.12 * Math.sin(u * 9 + seed) + (u > 1 ? 0.08 : 0);
      pts.push([x + Math.cos(a) * r * k * 1.08, y + Math.sin(a) * r * k * 0.92]);
    }
    lib.inkPath(ctx, pts, { width: o.width || 3.2, color: o.color || '#C8322B', alpha: 0.88, seed, wobble: 2.2, tremble: 0.8, taper: [4, 18] });
  };
})();
