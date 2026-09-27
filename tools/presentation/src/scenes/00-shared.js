// 00 общее для сцен: опорные кадры камеры, жизнь на улице, план посадок в разных стилях
(function () {
  const FILM = window.FILM, lib = FILM.lib, P = lib.pal, G = FILM.G, C = G.C, E = lib.ease;
  const clamp = lib.clamp;
  const TAU = Math.PI * 2;

  // опорные кадры: конец одного слайда совпадает с началом следующего
  G.CAMS = {
    city: G.mapCam(1000, 560, 1),
    cityEnd: G.mapCam(1025, 572, 1.08),
    team: G.mapCam(1710, 925, 3.1),
    mark: G.mapCam(G.MB[0], G.MB[1], 2.4),
    street: { x: 960, y: 540, z: 1 },
    tree: (() => {
      // крупный план: дерево ложится туда, где на крупном плане стоит посадка №3
      const c = G.TREE3;
      const z = 3.6;
      return { x: c.x + 420 / z, y: c.y - 60 / z, z, c };
    })(),
    ui: { x: 1250, y: 560, z: 0.9 },
  };

  /** Машины по полосам и пешеходы по тротуарам, движение на «двойках». */
  G.traffic = (ctx, t, o = {}) => {
    const tt = lib.onTwos(t);
    const cars = [
      { lane: 520, v: 70, x0: -200, c: '#C88C86' },
      { lane: 520, v: 70, x0: 700, c: '#9CC2EA' },
      { lane: 640, v: -55, x0: 1500, c: '#EFDCA3' },
      { lane: 640, v: -55, x0: 400, c: '#FBF6EA' },
    ];
    for (const car of cars) {
      const span = 2400;
      const x = (((car.x0 + car.v * tt + 300) % span) + span) % span - 300;
      const y = car.lane;
      const pts = lib.rrectPts(x - 46, y - 20, 92, 40, 12, 12);
      lib.inkPath(ctx, pts, { closed: true, width: 2.6, fill: car.c, seed: car.x0 + 3, wobble: 0.6, boilAmp: 0.7 / Math.max(1, G.zoomNow || 1) });
      const dir = Math.sign(car.v);
      ctx.fillStyle = lib.rgba(P.ink, 0.55);
      ctx.fillRect(x + dir * 18 - 7, y - 14, 14, 28);
    }
    if (o.people === false) return;
    // пешеходы: головы сверху, тень от солнца
    const r = lib.rng('people');
    for (let k = 0; k < 14; k++) {
      const top = k % 2 === 0;
      const y = top ? 250 + r() * 90 : 800 + r() * 90;
      const v = (r() < 0.5 ? -1 : 1) * (18 + r() * 16);
      const x = ((((r() * 2000 + v * tt) % 2100) + 2100) % 2100) - 90;
      ctx.fillStyle = lib.rgba(P.ink, 0.16);
      ctx.beginPath();
      ctx.ellipse(x + 5, y + 6, 8, 5, 0.6, 0, TAU);
      ctx.fill();
      ctx.fillStyle = [P.rose, P.teal, P.ochre, P.dusk][k % 4];
      ctx.beginPath();
      ctx.arc(x, y, 6, 0, TAU);
      ctx.fill();
      ctx.strokeStyle = P.ink;
      ctx.lineWidth = 1.5;
      ctx.stroke();
    }
  };

  /** Посадки плана поверх улицы. o.plain : без видов, o.trees / o.shrubs : доли появления. */
  G.plan = (ctx, o = {}) => {
    const tr = o.trees != null ? o.trees : 1;
    const sh = o.shrubs != null ? o.shrubs : 1;
    if (sh > 0) G.drawPlanShrubs(ctx, (k) => (typeof sh === 'function' ? sh(k) : sh));
    if (tr !== 0) G.drawPlanTrees(ctx, (k, c) => (typeof tr === 'function' ? tr(k, c) : tr), { plain: o.plain });
  };

  /** Улица линиями синьки: для вида издалека и для вариантов раскладки. */
  G.streetLines = (ctx, o = {}) => {
    G.drawSurfaceBlue(ctx, { alpha: o.alpha != null ? o.alpha : 0.7 });
  };

  /** Заголовок главы в углу: номер, название, одна строка. */
  G.chapterTitle = (ctx, t, num, title, o = {}) => {
    const blue = o.blue;
    const out = o.t1 != null ? 1 - G.seg(t, o.t1, 0.5, 'linear') : 1;
    if (out <= 0) return;
    ctx.save();
    ctx.globalAlpha *= out;
    const a = G.seg(t, o.t0 || 0.3, 0.4, 'linear');
    if (a > 0) {
      const w = G.measure(ctx, title, { size: 46, weight: 300 }) + 60;
      ctx.save();
      ctx.globalAlpha *= a;
      ctx.fillStyle = blue ? lib.rgba(P.navyLight, 0.92) : lib.rgba(P.paper, 0.93);
      ctx.fillRect(40, 26, w, 128);
      ctx.restore();
      lib.inkLine(ctx, 40, 154, 40 + w * a, 154, { width: 2.4, color: blue ? P.lavender : P.ink, seed: 12, alpha: a });
    }
    G.kicker(ctx, num, 70, 70, { color: blue ? P.lavender : P.inkSoft, p: G.seg(t, o.t0 || 0.3, 0.5, 'linear') });
    G.text(ctx, title, 66, 124, { size: 46, weight: 300, color: blue ? P.lineWhite : P.ink, p: G.seg(t, (o.t0 || 0.3) + 0.1, 0.9, 'linear') });
    ctx.restore();
  };

  /** Карточка-подпись с абзацем, появляется и уходит сама. */
  G.caption = (ctx, t, t0, t1, x, y, w, text, o = {}) => {
    const q = G.seg(t, t0, 0.4) * (t1 ? 1 - G.seg(t, t1, 0.3) : 1);
    if (q <= 0) return;
    const lines = G.lines(ctx, text, { size: o.size || 26, weight: 400, maxW: w - 72 });
    const lh = (o.size || 26) * 1.32;
    const h = lines.length * lh + (o.kick ? 88 : 56);
    G.card(ctx, x, y, w, h, { p: q, seed: o.seed || Math.round(x + y), blue: o.blue });
    let yy = y + 50;
    if (o.kick) {
      G.kicker(ctx, o.kick, x + 36, y + 46, { color: o.blue ? P.lavender : P.inkSoft, alpha: q });
      yy = y + 88;
    }
    G.para(ctx, text, x + 36, yy, { size: o.size || 26, weight: 400, maxW: w - 72, lh, color: o.blue ? P.lineWhite : P.ink, p: G.seg(t, t0 + 0.2, Math.max(1.2, lines.length * 0.6), 'linear'), alpha: q });
  };
})();
