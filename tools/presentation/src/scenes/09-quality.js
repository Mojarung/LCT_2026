// 09 качество: камера поднимается над улицей в ночную синьку; рядом встают ещё 7 раскладок,
// каждая получает свой индекс, выигрывает наибольший
(function () {
  const FILM = window.FILM, lib = FILM.lib, P = lib.pal, G = FILM.G, C = G.C, E = lib.ease;
  const clamp = lib.clamp;
  const TAU = Math.PI * 2;
  const S = G.street;
  const M = G.M;

  // src/green/application/params.py:30-41
  const TERMS = [
    ['плотность', 0.15], ['пригодность', 0.15], ['разнообразие', 0.10], ['ряды', 0.05], ['ярусность', 0.10],
    ['категория', 0.10], ['тень', 0.10], ['пылезащита', 0.10], ['запас до норм', 0.10], ['сезонность', 0.05],
  ];
  const TINT = [P.paleBlue, P.lavender, '#9CE6C6', '#F2C94C', '#FF8A5B', P.paleBlue, P.lavender, '#9CE6C6', '#F2C94C', '#FF8A5B'];
  const VARIANTS = ['baseline', 'joint', 'phase_x', 'phase_xy', 'aligned', 'aligned_joint', 'soil_frame', 'soil_frame_joint'];
  const WIN = 6; // слот, где лежит сама улица
  const DUR = 19;
  const SLOT = (i) => [((i % 4) - 2) * 2320, (Math.floor(i / 4) - 1) * 1700];
  G.SLOT = SLOT;
  G.VARIANT_PLANS = null;
  G.CAMS.high = { x: -1900, y: 600, z: 0.139 };

  // у каждого варианта свой сдвиг сетки; деревья проходят ту же проверку отступов
  const PLANS = VARIANTS.map((_, v) => {
    if (v === WIN) return G.ok.map((c) => [c.x, c.y]);
    const r = lib.rng('var' + v);
    const dx = (v * 23) % 60 - 30, dyA = [0, -10, 10][v % 3];
    return G.candidates
      .map((c) => [c.x + dx, c.y + (c.row === 'A' ? dyA : -dyA)])
      .filter(([x, y]) => {
        for (const n of S.nets) if (G.distPoly(x, y, n.pts) / M - (n.channel ? n.channel / 2 / M : 0) < G.RULES[n.key]) return false;
        for (const [px, py] of S.poles) if (Math.hypot(px - x, py - y) / M < G.RULES.pole) return false;
        return r() > 0.12;
      });
  });
  G.VARIANT_PLANS = PLANS;
  const SCORE = PLANS.map((p, v) => (v === WIN ? 1 : 0.55 + 0.4 * (p.length / (PLANS[WIN].length + 3))));

  function rosette(ctx, t, cx, cy) {
    const R0 = 100, R1 = 168;
    let a = -Math.PI / 2;
    TERMS.forEach(([name, w], i) => {
      const span = w * TAU;
      const q = G.seg(t, 1.6 + i * 0.28, 0.6, 'outCubic');
      const a0 = a + 0.025, a1 = a + span * q - 0.025;
      if (q > 0 && a1 > a0) {
        ctx.save();
        ctx.beginPath();
        ctx.arc(cx, cy, R1, a0, a1);
        ctx.arc(cx, cy, R0, a1, a0, true);
        ctx.closePath();
        ctx.fillStyle = lib.rgba(TINT[i], 0.22);
        ctx.fill();
        ctx.strokeStyle = lib.rgba(TINT[i], 0.9);
        ctx.lineWidth = 2;
        ctx.stroke();
        ctx.restore();
      }
      const am = a + span / 2;
      const lq = G.seg(t, 1.9 + i * 0.28, 0.5, 'linear');
      const right = Math.cos(am) >= 0;
      const lx = cx + Math.cos(am) * (R1 + 22), ly = cy + Math.sin(am) * (R1 + 22) + 6;
      G.text(ctx, name + ' ' + G.fmt(w, 2), lx, ly, { size: 17, weight: 500, color: P.lineWhite, align: right ? 'left' : 'right', alpha: lq });
      a += span;
    });
    lib.ticks(ctx, cx, cy, { r: R1 + 6, n: 100, len: 5, major: 10, majorLen: 12, color: P.lavender, alpha: 0.5, width: 1.2, start: -Math.PI / 2, rot: t * 0.05 });
    const cq = G.seg(t, 4.4, 0.6, 'linear');
    G.text(ctx, 'Q', cx, cy + 20, { size: 76, weight: 200, color: P.lineWhite, align: 'center', alpha: cq });
    G.text(ctx, '10 слагаемых', cx, cy + 52, { size: 16, weight: 500, family: G.MONO, color: P.lavender, align: 'center', alpha: cq });
  }

  function variants(ctx, t, cam) {
    ctx.save();
    G.applyCam(ctx, cam);
    VARIANTS.forEach((name, v) => {
      const [ox, oy] = SLOT(v);
      const q = v === WIN ? 1 : G.seg(t, 2.8 + v * 0.12, 0.6, 'linear');
      if (q <= 0) return;
      ctx.save();
      ctx.translate(ox, oy);
      ctx.globalAlpha *= q;
      ctx.fillStyle = lib.rgba(P.navyLight, 0.85);
      ctx.fillRect(0, 0, 1920, 1080);
      G.drawSurfaceBlue(ctx, { alpha: 0.6 });
      G.drawNetsBlue(ctx, { labels: false });
      ctx.fillStyle = lib.rgba(P.paleBlue, 0.95);
      for (const [x, y] of PLANS[v]) {
        ctx.beginPath();
        ctx.arc(x, y, 34, 0, TAU);
        ctx.fill();
      }
      ctx.strokeStyle = lib.rgba(P.lavender, 0.8);
      ctx.lineWidth = 1.5 / cam.z;
      ctx.strokeRect(0, 0, 1920, 1080);
      ctx.restore();
    });
    ctx.restore();
    VARIANTS.forEach((name, v) => {
      const [ox, oy] = SLOT(v);
      const [sx, sy] = G.toScreen(cam, ox, oy + 1080);
      const [ex] = G.toScreen(cam, ox + 1920, oy);
      const q = G.seg(t, 3.0 + v * 0.12, 0.5, 'linear');
      if (q <= 0) return;
      G.text(ctx, name, sx, sy + 22, { size: 16, weight: 500, family: G.MONO, color: v === WIN ? P.lineWhite : P.lavender, alpha: q });
      const bq = G.seg(t, 4.8 + v * 0.3, 0.6, 'outCubic');
      ctx.fillStyle = lib.rgba(P.lavender, 0.25);
      ctx.fillRect(sx, sy + 32, ex - sx, 5);
      ctx.fillStyle = v === WIN ? P.magenta : P.lavender;
      ctx.fillRect(sx, sy + 32, (ex - sx) * SCORE[v] * bq, 5);
      if (v === WIN && t > 7.6) {
        const [wx, wy] = G.toScreen(cam, ox, oy);
        const w = (ex - sx), h = sy - wy;
        ctx.save();
        ctx.strokeStyle = P.magenta;
        ctx.lineWidth = 3;
        ctx.strokeRect(wx - 6, wy - 6, w + 12, h + 12);
        ctx.restore();
        G.text(ctx, 'max Q', wx + w, wy - 14, { size: 18, weight: 600, family: G.MONO, color: P.magenta, align: 'right', alpha: G.seg(t, 7.6, 0.3, 'linear') });
        G.ring(ctx, wx + w / 2, wy + h / 2, w * 0.6, t, 7.6, { color: P.magenta, dur: 0.6 });
      }
    });
  }

  FILM.slide({
    id: 'quality',
    mode: 'blue',
    dur: DUR,
    tr: { kind: 'morph', dur: 0.4 },
    draw(ctx, t) {
      const cam = G.camPath([[0, G.CAMS.street], [0.45, G.CAMS.street], [3.0, G.CAMS.high, 'inOutSine']], t);
      const night = G.seg(t, 0.3, 1.6, 'inOutSine');
      lib.blueprint(ctx, { noise: 0, seed: 21, center: [960, 540] });
      // звёзды мерцают на ночной синьке
      for (let k = 0; k < 60; k++) {
        const r = lib.rng('star' + k);
        const x = r() * 1920, y = r() * 1080;
        const tw = 0.3 + 0.7 * Math.abs(Math.sin(t * (0.6 + r()) + k));
        ctx.fillStyle = lib.rgba(P.lineWhite, 0.5 * tw * night);
        ctx.fillRect(x, y, 2, 2);
      }
      if (night < 1) {
        // улица на бумаге растворяется, остаётся её чертёж
        ctx.save();
        ctx.globalAlpha *= 1 - night;
        G.world(ctx, cam, { t: t + 98, district: false });
        G.applyCam(ctx, cam);
        G.traffic(ctx, t + 108);
        G.shrubsFull(ctx);
        G.drawPlanTrees(ctx, () => 1);
        ctx.restore();
      }
      ctx.save();
      ctx.globalAlpha *= night;
      variants(ctx, t, cam);
      ctx.restore();
      const bl = night;
      if (bl < 1) G.chapters(ctx, t, 5, { dur: DUR, alpha: 1 - bl });
      if (bl > 0) G.chapters(ctx, t, 5, { blue: true, dur: DUR, alpha: bl });
      if (t < 1.0) return;
      const out = 1 - G.seg(t, DUR - 1.0, 0.6, 'linear');
      ctx.save();
      ctx.globalAlpha *= out;
      rosette(ctx, t, 300, 660);
      const tx = 700;
      G.para(ctx, 'До 8 раскладок проходят подбор видов, проверку и индекс. Побеждает наибольший Q, при равенстве меньше согласований.', tx, 710, { size: 23, weight: 400, maxW: 1150, lh: 32, color: P.lavender, p: G.seg(t, 8.4, 1.6, 'linear') });
      G.para(ctx, 'Ценность посадки = Q(план) - Q(план без неё), показана в промилле. Пока в плане есть запрещённая посадка, индекс не выставляется.', tx, 800, { size: 23, weight: 400, maxW: 1150, lh: 32, color: P.lavender, p: G.seg(t, 10.2, 1.8, 'linear') });
      G.para(ctx, 'Камчатская 0,53, Кустанайская 0,58, Песчаный 0,53. В экспериментах портфель ни разу не проиграл жадной раскладке, лучший прирост 0,510 → 0,618.', tx, 890, { size: 23, weight: 500, maxW: 1150, lh: 32, color: P.lineWhite, p: G.seg(t, 12.2, 2.0, 'linear') });
      ctx.restore();
      G.chapterTitle(ctx, t, '06 · КАЧЕСТВО', 'Из восьми раскладок остаётся одна', { blue: true, t0: 1.0, t1: DUR - 0.9 });
    },
  });
})();
