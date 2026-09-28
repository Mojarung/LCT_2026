// 05 размещение: лист ложится обратно, по улице идут станции, каждое место проверяется целиком,
// места, где не проходят отступы, уходят в отказ с причиной
(function () {
  const FILM = window.FILM, lib = FILM.lib, P = lib.pal, G = FILM.G, C = G.C, E = lib.ease;
  const clamp = lib.clamp;
  const S = G.street;
  const M = G.M;
  const BACK = [0.3, 1.9], DUR = 19;

  const ORDER = G.candidates.slice().sort((a, b) => a.x - b.x || a.y - b.y);
  const T0 = 3.8, DT = 0.26;
  const at = (c) => T0 + ORDER.indexOf(c) * DT;
  const DONE = T0 + ORDER.length * DT + 0.3;
  const FADE = DUR - 1.3; // отметки проверки гаснут, остаются деревья
  const offsetsA = [2, 2.5, 3].map((m) => S.curbA - m * M);
  const offsetsB = [2, 2.5, 3].map((m) => S.curbB + m * M);
  const short = { power: 'кабель', water: 'водопровод', pole: 'опора', gas: 'газ', sewer: 'канализ.', heat: 'теплосеть', telecom: 'связь' };

  function rays(ctx, c, q) {
    ctx.save();
    ctx.lineWidth = 2;
    ctx.setLineDash([6, 5]);
    for (const n of S.nets) {
      const [px, py] = G.nearestOnPoly(c.x, c.y, n.pts);
      if (Math.hypot(px - c.x, py - c.y) > 5 * M) continue;
      ctx.strokeStyle = lib.rgba(n.color === C.telecom ? P.annBlue : n.color, 0.95 * q);
      ctx.beginPath();
      ctx.moveTo(c.x, c.y);
      ctx.lineTo(lib.lerp(c.x, px, q), lib.lerp(c.y, py, q));
      ctx.stroke();
    }
    for (const [px, py] of S.poles) {
      if (Math.hypot(px - c.x, py - c.y) > 5 * M) continue;
      ctx.strokeStyle = lib.rgba(P.annYellow, q);
      ctx.beginPath();
      ctx.moveTo(c.x, c.y);
      ctx.lineTo(lib.lerp(c.x, px, q), lib.lerp(c.y, py, q));
      ctx.stroke();
    }
    ctx.restore();
    ctx.save();
    ctx.strokeStyle = lib.rgba(P.ink, 0.8 * q);
    ctx.lineWidth = 1.5;
    ctx.setLineDash([4, 4]);
    ctx.strokeRect(c.x - 1.1 * M, c.y - 1.1 * M, 2.2 * M, 2.2 * M);
    ctx.restore();
  }

  function street(ctx, t) {
    G.world(ctx, G.CAMS.street, { t: t + 62 });
    G.traffic(ctx, t + 42);
    // станции на трёх отступах от борта
    const sq = G.seg(t, 2.0, 1.2, 'inOutCubic');
    ctx.save();
    ctx.globalAlpha *= 1 - G.seg(t, FADE, 0.7, 'linear');
    for (const ys of [offsetsA, offsetsB]) {
      ys.forEach((y, i) => {
        ctx.strokeStyle = lib.rgba(P.annBlue, 0.55);
        ctx.setLineDash([3, 7]);
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        ctx.moveTo(0, y);
        ctx.lineTo(1920 * sq, y);
        ctx.stroke();
        ctx.setLineDash([]);
        ctx.fillStyle = lib.rgba(P.annBlue, 0.7);
        for (let x = 60 + i * 40; x < 1920 * sq; x += 120) {
          ctx.beginPath();
          ctx.arc(x, y, 3, 0, Math.PI * 2);
          ctx.fill();
        }
      });
    }
    ctx.restore();
    // проверка кандидатов
    for (const c of ORDER) {
      const t0 = at(c);
      if (t < t0) continue;
      const q = clamp((t - t0) / 0.35);
      if (t - t0 < 0.6) rays(ctx, c, E.outCubic(q));
      if (c.ok) {
        G.tree(ctx, c.x, c.y, 52, { s: G.pop(t, t0 + 0.3, 0.2), seed: c.id * 31 });
        G.ring(ctx, c.x, c.y, 60, t, t0 + 0.32, { color: P.annYellow });
      } else {
        G.cross(ctx, c.x, c.y, 13, { p: ((t - t0 - 0.3) / 0.2) * (1 - G.seg(t, FADE, 0.7, 'linear')) });
        const tagA = clamp((t - t0 - 0.3) / 0.12) * (1 - clamp((t - t0 - 0.75) / 0.2));
        if (tagA > 0) {
          const f = c.fails[0];
          const txt = `${short[f.key] || f.what} ${G.fmt(f.d, 1)} < ${G.fmt(f.need, 1)} м`;
          const lvl = ORDER.indexOf(c) % 2;
          const ty = c.row === 'A' ? c.y - 56 - lvl * 32 : c.y + 70 + lvl * 32;
          const w = G.measure(ctx, txt, { size: 17, weight: 500, family: G.MONO }) + 18;
          ctx.save();
          ctx.globalAlpha *= tagA;
          ctx.fillStyle = P.annMagenta;
          ctx.fillRect(c.x - w / 2, ty - 20, w, 28);
          ctx.restore();
          G.text(ctx, txt, c.x, ty, { size: 17, weight: 500, family: G.MONO, color: P.white, align: 'center', alpha: tagA });
        }
      }
    }
  }

  FILM.slide({
    id: 'placement',
    mode: 'paper',
    dur: DUR,
    tr: { kind: 'morph', dur: 0.4 },
    draw(ctx, t) {
      const q = 1 - G.seg(t, BACK[0], BACK[1] - BACK[0], 'linear');
      // под листом та же синька, что в конце прошлого слайда, и она продолжает жить
      G.peel(ctx, q, (c) => G.undergroundScene(c, 19 + t), (c) => street(c, t));
      const bl = lib.clamp((q - 0.35) / 0.35);
      if (bl < 1) G.chapters(ctx, t, 2, { dur: DUR, alpha: 1 - bl });
      if (bl > 0) G.chapters(ctx, t, 2, { blue: true, dur: DUR, alpha: bl });
      if (q > 0) return;
      G.chapterTitle(ctx, t, '03 · РАЗМЕЩЕНИЕ', 'Место проверяется целиком', { t0: BACK[1], t1: DUR - 0.8 });
      G.caption(ctx, t, 2.2, 11.2, 1180, 880, 700, 'Станции вдоль борта через 5 м на отступах 3, 2,5 и 2 м и сетка по газону. Яма дерева 2,2 × 2,2 м проверяется по всем 62 отступам сразу.', { size: 23, seed: 9 });
      G.caption(ctx, t, 11.6, DUR - 0.9, 1180, 850, 700, 'Где под газоном кабель, водопровод или рядом опора, место уходит в отказ: причина и недобор до нормы остаются в объяснении. Берзарина: 68 190 кандидатов у борта, 1 871 на газоне.', { size: 23, seed: 11 });
    },
  });
})();
