// 11 нормоконтроль: та же улица пополам; слева план «как у проектировщика», его правит красный карандаш,
// справа план сервиса
(function () {
  const FILM = window.FILM, lib = FILM.lib, P = lib.pal, G = FILM.G, C = G.C, E = lib.ease;
  const clamp = lib.clamp;
  const HALF = 960;
  const DESIGNER = G.candidates.filter((c) => c.x < HALF);
  const BY_RULE = [['силовой кабель', 159], ['бортовой камень', 104], ['опоры', 77], ['водопровод', 71], ['кабель связи', 62]];

  FILM.slide({
    id: 'audit',
    mode: 'paper',
    dur: 19,
    tr: { kind: 'scan', dur: 1.3, ring: '#C8322B' },
    draw(ctx, t) {
      const fix = G.seg(t, 17.0, 1.4, 'inOutCubic');
      const SPLIT = HALF * (1 - fix);
      const cardsA = 1 - G.seg(t, 16.7, 0.5, 'linear');
      G.world(ctx, G.CAMS.street, { t: t + 150 });
      G.traffic(ctx, t);
      // справа наш план целиком
      ctx.save();
      ctx.beginPath();
      ctx.rect(SPLIT, 0, 1920 - SPLIT, 1080);
      ctx.clip();
      G.shrubsFull(ctx);
      G.drawPlanTrees(ctx, () => 1);
      ctx.restore();
      // слева деревья на каждом месте через 6 м, без оглядки на сети
      ctx.save();
      ctx.beginPath();
      ctx.rect(0, 0, SPLIT, 1080);
      ctx.clip();
      ctx.fillStyle = lib.rgba('#F3E1D8', 0.35);
      ctx.fillRect(0, 0, SPLIT, 1080);
      DESIGNER.forEach((c, k) => G.tree(ctx, c.x, c.y, k % 5 === 4 ? 44 : 52, { s: G.pop(t, 0.5 + k * 0.08, 0.2), kind: k % 5 === 4 ? 'conifer' : 'leaf', seed: c.id * 13, fill: '#A9B98A', deep: '#6E7F52' }));
      // красный карандаш обводит каждое нарушение и пишет недобор
      DESIGNER.forEach((c, k) => {
        if (c.ok) return;
        const t0 = 2.6 + k * 0.3;
        G.scribble(ctx, c.x, c.y, 62, G.seg(t, t0, 0.35, 'linear'), 900 + k);
        const f = c.fails[0];
        const lq = G.seg(t, t0 + 0.3, 0.3, 'linear');
        if (lq > 0) {
          const y = c.row === 'A' ? c.y - 78 - (k % 2) * 26 : c.y + 92 + (k % 2) * 26;
          G.text(ctx, '-' + G.fmt(f.need - f.d, 1) + ' м', c.x, y, { size: 22, weight: 700, italic: true, color: '#C8322B', align: 'center', alpha: lq });
        }
      });
      ctx.restore();
      if (SPLIT > 2) {
        lib.inkLine(ctx, SPLIT, 0, SPLIT, 1080, { width: 5, seed: 71 });
        lib.inkLine(ctx, SPLIT + 9, 0, SPLIT + 9, 1080, { width: 1.5, seed: 72, alpha: 0.5 });
      }
      ctx.save();
      ctx.globalAlpha *= cardsA;

      const hq = G.seg(t, 0.3, 0.4);
      G.card(ctx, 40, 30, 880, 150, { p: hq, seed: 61 });
      G.card(ctx, HALF + 40, 30, 880, 150, { p: hq, seed: 62 });
      if (hq > 0) {
        G.kicker(ctx, 'НОРМОКОНТРОЛЬ · ПЛАН ПРОЕКТИРОВЩИКА, БЕРЗАРИНА', 76, 78, { color: '#C8322B', alpha: hq });
        G.text(ctx, '554 посадки, у 391 нарушен отступ', 76, 134, { size: 36, weight: 400, color: P.ink, p: G.seg(t, 0.6, 0.8, 'linear') });
        G.kicker(ctx, 'ПЛАН СЕРВИСА · ТА ЖЕ УЛИЦА', HALF + 76, 78, { color: P.tealDeep, alpha: hq });
        G.text(ctx, '860 посадок, 0 нарушений', HALF + 76, 134, { size: 36, weight: 400, color: P.ink, p: G.seg(t, 0.9, 0.8, 'linear') });
      }
      const bq = G.seg(t, 7.6, 0.4);
      G.card(ctx, 40, 760, 880, 280, { p: bq, seed: 63 });
      if (bq > 0) {
        G.text(ctx, '785 нарушений по правилам', 76, 810, { size: 24, weight: 500, color: P.ink, alpha: bq });
        BY_RULE.forEach(([name, n], i) => {
          const q = G.seg(t, 7.9 + i * 0.2, 0.8, 'outCubic');
          const y = 850 + i * 38;
          G.text(ctx, name, 76, y + 8, { size: 20, weight: 400, color: P.inkSoft, alpha: bq });
          ctx.fillStyle = lib.rgba('#C8322B', 0.8);
          ctx.fillRect(330, y - 10, (n / 159) * 440 * q, 22);
          G.text(ctx, String(Math.round(n * q)), 340 + (n / 159) * 440 * q, y + 8, { size: 19, weight: 600, family: G.MONO, color: P.ink, alpha: bq });
        });
      }
      const cq = G.seg(t, 9.6, 0.4);
      G.card(ctx, HALF + 40, 760, 880, 280, { p: cq, seed: 64 });
      if (cq > 0) {
        G.text(ctx, '$ green audit план.dxf --plantings "^0?6_+ДП_.+_план$"', HALF + 76, 818, { size: 19, weight: 500, family: G.MONO, color: P.ink, p: G.seg(t, 9.8, 1.2, 'linear') });
        G.para(ctx, 'Те же правила проверяют чужой план. На выходе audit.dxf с отметками на слоях GREEN_AUDIT_* и audit.md с пунктом акта и недобором в метрах. У плана сервиса 3 посадки на согласование: охранная зона воздушной линии.', HALF + 76, 866, { size: 21, weight: 400, maxW: 810, lh: 29, color: P.inkSoft, p: G.seg(t, 10.8, 2.2, 'linear') });
      }
      ctx.restore();
    },
  });
})();
