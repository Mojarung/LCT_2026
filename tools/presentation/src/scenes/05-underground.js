// 04 нормы: лист улицы отгибается, под ним синька с живыми сетями; каждая сеть обрастает полосой отступа
(function () {
  const FILM = window.FILM, lib = FILM.lib, P = lib.pal, G = FILM.G, C = G.C, E = lib.ease;
  const clamp = lib.clamp;
  const S = G.street;
  const M = G.M;
  const PEEL = [0.5, 2.6], DUR = 19;

  const YAML = [
    ['- rule_id: ', 'R-POWER-TREE-001'],
    ['  object_class: ', 'utility.power_cable'],
    ['  planting_type: ', 'tree'],
    ['  min_distance_m: ', '2.0'],
    ['  measure_to: ', 'outer_wall'],
    ['  citation:', ''],
    ['    act_id: ', 'SP42_13330_2016'],
    ['    clause: ', '"п. 9.6, табл. 9.1: подземные сети,'],
    ['            ', ' силовой кабель; прим. 5"'],
    ['    status: ', 'verified'],
  ];
  const TABLE = [
    ['стена здания', '5,0', '1,5'],
    ['силовой кабель, связь', '2,0', '0,7'],
    ['водопровод', '2,0', '-'],
    ['газ, канализация', '1,5', '-'],
    ['теплосеть', '2,0', '1,0'],
    ['опора освещения', '4,0', '-'],
  ];

  // длина ломаной и точка на ней по доле
  const pathLen = (pts) => pts.slice(1).reduce((a, p, i) => a + Math.hypot(p[0] - pts[i][0], p[1] - pts[i][1]), 0);
  function along(pts, u) {
    const L = pathLen(pts) * u;
    let acc = 0;
    for (let i = 0; i + 1 < pts.length; i++) {
      const d = Math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1]);
      if (acc + d >= L) {
        const q = (L - acc) / d;
        return [lib.lerp(pts[i][0], pts[i + 1][0], q), lib.lerp(pts[i][1], pts[i + 1][1], q)];
      }
      acc += d;
    }
    return pts[pts.length - 1];
  }

  // по сетям бежит то, что по ним течёт: вода, ток, газ, тепло
  function flow(ctx, t, q) {
    if (q <= 0) return;
    const speed = { power: 0.16, telecom: 0.22, water: 0.06, gas: 0.05, heat: 0.04, sewer: 0.03 };
    for (const n of S.nets) {
      const cnt = 9;
      for (let k = 0; k < cnt; k++) {
        const u = (((k / cnt + t * speed[n.key] * (n.key === 'heat' ? -1 : 1)) % 1) + 1) % 1;
        const [x, y] = along(n.pts, u);
        if (n.key === 'power' || n.key === 'telecom') lib.glowDot(ctx, x, y, 3.5, { color: n.color, rays: 4, glow: 5, intensity: q, seed: k });
        else {
          ctx.fillStyle = lib.rgba(n.color, 0.9 * q);
          ctx.beginPath();
          ctx.ellipse(x, y, 11, 3.2, 0, 0, Math.PI * 2);
          ctx.fill();
        }
      }
    }
  }

  function band(ctx, pts, half, color, q) {
    if (q <= 0) return;
    const h = half * E.outCubic(q);
    ctx.save();
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';
    ctx.strokeStyle = lib.rgba(color, 0.18);
    ctx.lineWidth = h * 2;
    ctx.beginPath();
    lib.tracePath(ctx, pts, false);
    ctx.stroke();
    ctx.setLineDash([10, 8]);
    ctx.lineWidth = 1.5;
    ctx.strokeStyle = lib.rgba(color, 0.8 * q);
    for (const s of [-1, 1]) {
      ctx.beginPath();
      lib.tracePath(ctx, pts.map(([x, y]) => [x, y + s * h]), false);
      ctx.stroke();
    }
    ctx.restore();
  }

  function underground(ctx, t) {
    lib.blueprint(ctx, { noise: 0, seed: 11, center: [1300, 560] });
    // слои грунта: горизонтальные разрезы с редкой штриховкой
    ctx.save();
    ctx.strokeStyle = lib.rgba(P.lavender, 0.06);
    ctx.lineWidth = 1;
    ctx.beginPath();
    for (let y = 20; y < 1080; y += 14) {
      ctx.moveTo(0, y + 4 * Math.sin(y * 0.05));
      ctx.lineTo(1920, y + 4 * Math.sin(y * 0.05 + 2));
    }
    ctx.stroke();
    ctx.restore();
    G.drawSurfaceBlue(ctx, { alpha: 0.35 });
    // полосы отступов по очереди
    const T0 = 3.8;
    S.nets.forEach((n, i) => band(ctx, n.pts, G.RULES[n.key] * M + (n.channel || 0) / 2, n.color, G.seg(t, T0 + i * 0.45, 0.6)));
    const qp = G.seg(t, T0 + 2.8, 0.6);
    if (qp > 0) {
      for (const [x, y] of S.poles) {
        ctx.save();
        ctx.fillStyle = lib.rgba(P.lineWhite, 0.1);
        ctx.strokeStyle = lib.rgba(P.lineWhite, 0.7);
        ctx.setLineDash([8, 6]);
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        ctx.arc(x, y, G.RULES.pole * M * E.outBack(qp), 0, Math.PI * 2);
        ctx.fill();
        ctx.stroke();
        ctx.restore();
      }
    }
    G.drawNetsBlue(ctx, { p: G.seg(t, 1.2, 1.6, 'inOutCubic'), labelX: 830 });
    flow(ctx, t, G.seg(t, 2.4, 0.8, 'linear'));
    const tags = [['2,0 м', 300, C.power, 0], ['2,0 м', 636, C.heat, 4], ['1,5 м', 560, C.sewer, 5], ['2,0 м', 846, C.water, 2]];
    for (const [s, y, col, i] of tags) {
      const q = G.seg(t, T0 + i * 0.45 + 0.4, 0.4, 'linear');
      if (q > 0) G.text(ctx, s, 1880, y - 10, { size: 20, weight: 600, family: G.MONO, color: col, align: 'right', alpha: q });
    }
    if (qp > 0.4) G.text(ctx, '4,0 м', 1690, 440, { size: 20, weight: 600, family: G.MONO, color: P.lineWhite, alpha: qp });
  }

  G.undergroundScene = underground;

  function card(ctx, t) {
    const cq = G.seg(t, 2.6, 0.5, 'linear') * (1 - G.seg(t, DUR - 0.9, 0.5, 'linear'));
    if (cq <= 0) return;
    ctx.save();
    ctx.globalAlpha *= cq;
    G.card(ctx, 40, 186, 740, 856, { blue: true, p: cq });
    YAML.forEach(([k, v], i) => {
      const q = G.seg(t, 3.0 + i * 0.22, 0.35, 'linear');
      if (q <= 0) return;
      const y = 240 + i * 28;
      G.text(ctx, k, 76, y, { size: 19, weight: 400, family: G.MONO, color: P.lavender, alpha: q });
      const w = G.measure(ctx, k, { size: 19, weight: 400, family: G.MONO });
      G.text(ctx, v, 76 + w, y, { size: 19, weight: 500, family: G.MONO, color: i === 3 ? P.magenta : P.lineWhite, p: q });
    });
    const ty = 560;
    const hq = G.seg(t, 5.6, 0.5, 'linear');
    G.text(ctx, 'объект', 76, ty, { size: 17, weight: 500, family: G.MONO, color: P.lavender, alpha: hq });
    G.text(ctx, 'дерево', 560, ty, { size: 17, weight: 500, family: G.MONO, color: P.lavender, alpha: hq, align: 'right' });
    G.text(ctx, 'кустарник', 740, ty, { size: 17, weight: 500, family: G.MONO, color: P.lavender, alpha: hq, align: 'right' });
    TABLE.forEach(([o, a, b], i) => {
      const q = G.seg(t, 5.8 + i * 0.32, 0.45, 'linear');
      if (q <= 0) return;
      const y = ty + 42 + i * 38;
      G.text(ctx, o, 76, y, { size: 22, weight: 400, color: P.lineWhite, p: q });
      G.text(ctx, a + ' м', 560, y, { size: 22, weight: 500, family: G.MONO, color: P.lineWhite, align: 'right', alpha: q });
      G.text(ctx, b === '-' ? '-' : b + ' м', 740, y, { size: 22, weight: 500, family: G.MONO, color: P.lavender, align: 'right', alpha: q });
    });
    G.para(ctx, '76 правил, из них 46 отступов. У 75 основание сверено по тексту акта. 84 дословные цитаты, в текстах заказчика найдена 81 из 81 доступной.', 76, 880, { size: 22, weight: 400, maxW: 670, lh: 30, color: P.lavender, p: G.seg(t, 8.4, 2.0, 'linear') });
    ctx.restore();
  }

  FILM.slide({
    id: 'underground',
    mode: 'blue',
    dur: DUR,
    tr: { kind: 'morph', dur: 0.4 },
    draw(ctx, t) {
      const q = G.seg(t, PEEL[0], PEEL[1] - PEEL[0], 'linear');
      G.peel(ctx, q, (c) => underground(c, t), (c) => {
        G.world(c, G.CAMS.street, { t: t + 43, team: 1 });
        G.traffic(c, t + 23);
      });
      // линейка меняет бумагу на синьку вместе с листом
      const bl = lib.clamp((q - 0.35) / 0.35);
      if (bl < 1) G.chapters(ctx, t, 1, { dur: DUR, alpha: 1 - bl });
      if (bl > 0) G.chapters(ctx, t, 1, { blue: true, dur: DUR, alpha: bl });
      if (q < 1) return;
      card(ctx, t);
      G.chapterTitle(ctx, t, '02 · НОРМЫ', 'Под газоном кабели и трубы', { blue: true, t0: PEEL[1], t1: DUR - 0.8 });
    },
  });
})();
