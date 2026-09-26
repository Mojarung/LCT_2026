// 10 сверка: камера возвращается к победившей раскладке, на неё ложатся девять слоёв GREEN_*,
// по исходнику проходит луч отпечатков
(function () {
  const FILM = window.FILM, lib = FILM.lib, P = lib.pal, G = FILM.G, C = G.C, E = lib.ease;
  const clamp = lib.clamp;
  const TAU = Math.PI * 2;
  const S = G.street;
  const CAM = { x: 1452, y: 540, z: 0.62 };
  const DROP = 2.6, SCAN = [6.6, 3.4], DUR = 19;

  function layerContent(ctx, name, q) {
    if (q <= 0) return;
    ctx.save();
    ctx.globalAlpha *= q;
    if (name === 'GREEN_TREES') for (const c of G.trees) {
      ctx.fillStyle = lib.rgba(lib.mix(c.sp.fill, P.paleBlue, 0.4), 0.85);
      ctx.strokeStyle = P.lineWhite;
      ctx.lineWidth = 3;
      ctx.beginPath();
      ctx.arc(c.x, c.y, c.sp.r, 0, TAU);
      ctx.fill();
      ctx.stroke();
      ctx.fillStyle = P.navy;
      ctx.beginPath();
      ctx.arc(c.x, c.y, 6, 0, TAU);
      ctx.fill();
    }
    if (name === 'GREEN_SHRUBS') {
      ctx.fillStyle = lib.rgba('#9CE6C6', 0.8);
      for (const c of G.shrubSpots) for (let i = -1; i <= 1; i++) for (let j = -1; j <= 1; j++) {
        ctx.beginPath();
        ctx.arc(c.x + i * 20, c.y + j * 20, 8, 0, TAU);
        ctx.fill();
      }
    }
    if (name === 'GREEN_REJECT') for (const c of G.rejected) G.cross(ctx, c.x + 30, c.y - 30, 8, { color: P.magenta, width: 3 });
    if (name === 'GREEN_LABELS') G.trees.forEach((c, k) => G.text(ctx, String(k + 1), c.x + c.sp.r * 0.7, c.y - c.sp.r * 0.7, { size: 26, weight: 600, family: G.MONO, color: P.lineWhite }));
    if (name === 'GREEN_ZONE_ALLOWED') {
      for (const [y0, y1] of [S.lawnA, S.lawnB]) lib.hatch(ctx, G.rectPoly(1200, y0 + 6, 1920, y1 - 6), { spacing: 12, width: 2, color: P.paleBlue, alpha: 0.45, seed: y0, angle: -0.8 });
    }
    ctx.restore();
  }

  FILM.slide({
    id: 'result',
    mode: 'blue',
    dur: DUR,
    tr: { kind: 'morph', dur: 0.4 },
    draw(ctx, t) {
      const cam = G.camPath([[0, G.CAMS.high], [0.45, G.CAMS.high], [2.4, CAM, 'inOutSine']], t);
      lib.blueprint(ctx, { noise: 0, seed: 21, center: [960, 540] });
      ctx.save();
      G.applyCam(ctx, cam);
      // остальные раскладки гаснут
      const fade = 1 - G.seg(t, 0.1, 0.9, 'linear');
      for (let v = 0; v < 8; v++) {
        const [ox, oy] = G.SLOT(v);
        const own = ox === 0 && oy === 0;
        if (!own && fade <= 0) continue;
        ctx.save();
        ctx.translate(ox, oy);
        ctx.globalAlpha *= own ? 1 : fade;
        ctx.fillStyle = lib.rgba(P.navyLight, 0.85);
        ctx.fillRect(0, 0, 1920, 1080);
        G.drawSurfaceBlue(ctx, { alpha: 0.6 });
        G.drawNetsBlue(ctx, { labels: false });
        if (!own || t < DROP) {
          ctx.fillStyle = lib.rgba(P.paleBlue, 0.95 * (own ? 1 - G.seg(t, DROP - 0.3, 0.3, 'linear') : 1));
          for (const [x, y] of G.VARIANT_PLANS[v]) {
            ctx.beginPath();
            ctx.arc(x, y, 34, 0, TAU);
            ctx.fill();
          }
        }
        ctx.strokeStyle = lib.rgba(P.lavender, 0.8);
        ctx.lineWidth = 1.5 / cam.z;
        ctx.strokeRect(0, 0, 1920, 1080);
        ctx.restore();
      }
      // девять листов GREEN_* ложатся сверху
      G.LAYERS.forEach((name, i) => {
        const t0 = DROP + i * 0.36;
        const q = G.seg(t, t0, 0.4, 'outCubic');
        if (q <= 0) return;
        layerContent(ctx, name, G.seg(t, t0 + 0.3, 0.3, 'linear'));
        const land = 1 - G.seg(t, t0 + 0.4, 0.5, 'linear');
        if (land <= 0) return;
        ctx.save();
        const k = 1.25 - 0.25 * q;
        ctx.translate(960, 540 - (1 - q) * 500);
        ctx.scale(k, k);
        ctx.translate(-960, -540);
        ctx.fillStyle = lib.rgba(P.paleBlue, 0.1 * land);
        ctx.fillRect(0, 0, 1920, 1080);
        ctx.strokeStyle = lib.rgba(P.lineWhite, 0.9 * land);
        ctx.lineWidth = 3 / cam.z;
        ctx.strokeRect(0, 0, 1920, 1080);
        G.text(ctx, name, 30, -30, { size: 44, weight: 600, family: G.MONO, color: P.lineWhite, alpha: land * (1 - q * 0.85) });
        ctx.restore();
      });
      // луч отпечатков по исходнику
      const bq = G.seg(t, SCAN[0], SCAN[1], 'inOutSine');
      if (bq > 0) {
        const bx = bq * 2000 - 40;
        lib.hexLattice(ctx, G.rectPoly(0, 0, Math.min(1920, bx), 1080), { r: 44, alpha: 0.35, width: 2, seed: 3, cellFn: () => ({ fill: P.paleBlue, alpha: 0.08 }) });
        if (bq < 1) {
          ctx.strokeStyle = P.glow;
          ctx.lineWidth = 4 / cam.z;
          ctx.beginPath();
          ctx.moveTo(bx, -40);
          ctx.lineTo(bx, 1120);
          ctx.stroke();
        }
      }
      ctx.restore();
      if (bq > 0 && bq < 1) {
        const [sx, sy] = G.toScreen(cam, bq * 2000 - 40, -40);
        lib.glowDot(ctx, sx, sy, 7, { rays: 8 });
      }
      const n = Math.round(206860 * bq);
      if (bq > 0) G.text(ctx, G.num(n) + ' из 206 860 без изменений', 655, 930, { size: 26, weight: 500, family: G.MONO, color: P.lineWhite, align: 'center' });

      G.chapters(ctx, t, 6, { blue: true, dur: DUR });
      if (t < 1.5) return;
      const rx = 1300;
      G.para(ctx, 'Результат пишется в .result.pending.dxf и становится result.dxf после двух проверок: отпечатки blake2b исходника и обратное чтение посадок.', rx, 250, { size: 23, weight: 400, maxW: 560, lh: 32, color: P.lavender, p: G.seg(t, 2.6, 2.0, 'linear') });
      G.para(ctx, 'Вне слоёв GREEN_* не добавлено ничего. Весь прогон Берзарина занял 149 с.', rx, 440, { size: 23, weight: 400, maxW: 560, lh: 32, color: P.lavender, p: G.seg(t, 6.8, 1.4, 'linear') });
      G.para(ctx, 'Однажды проверка нашла в исходнике лишний блок стрелки от ezdxf. Исправлено, на это есть регрессионный тест.', rx, 560, { size: 23, weight: 400, maxW: 560, lh: 32, color: P.lavender, p: G.seg(t, 9.2, 1.8, 'linear') });
      const sq = G.seg(t, 11.4, 0.5);
      G.card(ctx, rx - 20, 710, 580, 220, { blue: true, p: sq });
      if (sq > 0) {
        G.kicker(ctx, 'ВСЕ УЛИЦЫ КАТАЛОГА', rx + 14, 758, { color: P.lavender, alpha: sq });
        G.text(ctx, '19 прогонов, 29 391 посадка', rx + 14, 812, { size: 32, weight: 300, color: P.lineWhite, p: G.seg(t, 11.6, 1.0, 'linear') });
        G.para(ctx, 'Целостность цела у каждой улицы. Время от 71 до 723 с, медиана 268 с.', rx + 14, 860, { size: 21, weight: 400, maxW: 530, lh: 28, color: P.lavender, p: G.seg(t, 12.4, 1.4, 'linear') });
      }
      G.chapterTitle(ctx, t, '07 · СВЕРКА', 'Исходник не тронут, и это проверено', { blue: true, t0: 1.4 });
    },
  });
})();
