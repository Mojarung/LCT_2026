// 07 виды: кроны перекрашиваются волной; где квота вида исчерпана, дерево уступает место группе
// кустарника; снизу выезжает гербарий с формулой MILP
(function () {
  const FILM = window.FILM, lib = FILM.lib, P = lib.pal, G = FILM.G, C = G.C, E = lib.ease;
  const clamp = lib.clamp;
  const TAU = Math.PI * 2;
  const DUR = 20, SHEET = 9.6; // гербарий выезжает
  const QUOTA = 3.8; // места, пустые по квотам
  const EMPTY = G.shrubSpots;
  const qAt = (c) => QUOTA + EMPTY.indexOf(c) * 0.4;
  const SPEC = G.SPECIES.slice(0, 6);

  function trees(ctx, t) {
    G.ok.forEach((c, k) => {
      const q = G.seg(t, 0.5 + (c.x / 1920) * 1.6 + (c.row === 'B' ? 0.15 : 0), 0.45, 'inOutCubic');
      const sp = c.sp;
      const fill = lib.mix(C.crown, sp.fill, q);
      const deep = lib.mix(C.crownDeep, sp.deep, q);
      const conifer = sp.kind === 'conifer' && q > 0.5;
      let r = lib.lerp(52, sp.r, q) * (1 + 0.08 * Math.sin(Math.PI * q));
      if (c.empty) r *= 1 - G.seg(t, qAt(c) + 0.6, 0.4, 'inBack');
      if (r > 1) G.tree(ctx, c.x, c.y, r, { kind: conifer ? 'conifer' : 'leaf', fill, deep, seed: c.id * 31 });
      if (c.empty) {
        const ta = G.seg(t, qAt(c), 0.25, 'linear') * (1 - G.seg(t, qAt(c) + 1.6, 0.4, 'linear'));
        if (ta > 0) {
          const y = c.y + 8;
          ctx.save();
          ctx.globalAlpha *= ta;
          ctx.fillStyle = P.annBlue;
          ctx.fillRect(c.x - 58, y - 22, 116, 30);
          ctx.restore();
          G.text(ctx, 'квота вида', c.x, y, { size: 17, weight: 600, family: G.MONO, color: P.white, align: 'center', alpha: ta });
        }
      }
      const la = G.seg(t, 0.8 + (c.x / 1920) * 1.6, 0.4, 'linear') * (1 - G.seg(t, SHEET - 0.6, 0.5, 'linear')) * (c.empty ? 1 - G.seg(t, qAt(c), 0.3, 'linear') : 1);
      if (la > 0) {
        const lvl = G.trees.indexOf(c) % 2;
        const y = c.row === 'A' ? c.y - sp.r - 14 - lvl * 22 : c.y + sp.r + 28 + lvl * 22;
        G.text(ctx, sp.lat, c.x, y, { size: 16, weight: 500, italic: true, color: P.ink, align: 'center', alpha: la });
      }
    });
  }

  // листья падают на «двойках», каждый своей дорогой
  function leaves(ctx, t) {
    const tt = lib.onTwos(t);
    for (let k = 0; k < 22; k++) {
      const r = lib.rng('leaf' + k);
      const period = 9 + r() * 6;
      const u = ((tt + r() * period) % period) / period;
      const x = r() * 2000 - 40 + Math.sin(u * TAU * 1.5 + k) * 60;
      const y = -40 + u * 1160;
      const a = u * TAU * (1 + r()) + k;
      const s = 9 + r() * 7;
      ctx.save();
      ctx.translate(x, y);
      ctx.rotate(a);
      lib.inkPath(ctx, [[-s, 0], [0, -s * 0.45], [s, 0], [0, s * 0.45]], { closed: true, width: 1.4, fill: [C.crown, '#C8B27A', '#C38F2E', C.crownPale][k % 4], seed: k, smooth: true, wobble: 0.3 });
      lib.inkLine(ctx, -s, 0, s, 0, { width: 1, seed: k + 50, alpha: 0.6 });
      ctx.restore();
    }
  }

  function specimen(ctx, t, sp, i, x, y, w, h, t0) {
    const q = G.seg(t, t0 + i * 0.15, 0.5, 'linear');
    if (q <= 0) return;
    ctx.save();
    ctx.globalAlpha *= clamp(q * 2);
    ctx.fillStyle = lib.rgba(P.white, 0.75);
    ctx.fillRect(x, y, w, h);
    lib.inkPath(ctx, lib.rectPts(x, y, w, h, 30), { closed: true, width: 1.5, seed: 60 + i, smooth: false, wobble: 0.6, alpha: 0.8 });
    // полоска скотча
    ctx.fillStyle = lib.rgba('#F4E9C8', 0.85);
    ctx.save();
    ctx.translate(x + w / 2, y);
    ctx.rotate(((i % 2) - 0.5) * 0.12);
    ctx.fillRect(-34, -10, 68, 20);
    ctx.restore();
    ctx.restore();
    const cx = x + w / 2, cy = y + 80;
    lib.guideCircle(ctx, cx, cy, 58, { color: P.inkFaint, alpha: 0.35, width: 1.2, cross: 6, p: q });
    G.tree(ctx, cx, cy, Math.min(50, sp.r), { s: G.pop(t, t0 + 0.2 + i * 0.15, 0.22), kind: sp.kind, fill: sp.fill, deep: sp.deep, seed: 200 + i });
    G.para(ctx, sp.ru, x + 14, y + 170, { size: 18, weight: 600, maxW: w - 24, lh: 22, color: P.ink, p: q });
    const n = G.lines(ctx, sp.ru, { size: 18, weight: 600, maxW: w - 24 }).length;
    G.text(ctx, sp.lat, x + 14, y + 172 + n * 22, { size: 16, weight: 400, italic: true, color: P.inkSoft, p: q });
    G.text(ctx, sp.h + ' м · ' + sp.fam, x + 14, y + 194 + n * 22, { size: 13, weight: 500, family: G.MONO, color: P.inkFaint, p: q });
  }

  function herbarium(ctx, t) {
    const q = G.seg(t, SHEET, 0.9, 'outCubic') * (1 - G.seg(t, DUR - 1.7, 0.9, 'inCubic'));
    if (q <= 0) return;
    const top = lib.lerp(1100, 560, q);
    // крафт с рваным краем: растр строится один раз
    const kraft = G.cachedCanvas('kraft', (g) => {
      g.fillStyle = '#D8C29A';
      g.beginPath();
      g.moveTo(-20, 30);
      for (let x = -20; x <= 1940; x += 24) g.lineTo(x, 8 + 10 * lib.noise1(x * 0.02, 3) + 6 * lib.noise1(x * 0.11, 4));
      g.lineTo(1940, 1080);
      g.lineTo(-20, 1080);
      g.closePath();
      g.fill();
      lib.stipple(g, lib.rectPts(0, 30, 1920, 1000, 60), { spacing: 11, r: [0.6, 1.4], color: '#8E7440', alpha: 0.35, seed: 5, density: 0.5 });
    }, { boil: false });
    ctx.drawImage(kraft, 0, top, 1920, 1080);
    const y = top + 56;
    SPEC.forEach((sp, i) => specimen(ctx, t, sp, i, 50 + i * 186, y, 176, 262, SHEET + 0.5));
    // формула и числа
    const fx = 1190;
    const fq = G.seg(t, SHEET + 1.2, 0.4);
    G.card(ctx, fx, y - 6, 690, 280, { p: fq, seed: 41 });
    if (fq > 0) {
      G.kicker(ctx, 'MILP · HiGHS', fx + 30, y + 38, { color: P.inkSoft, alpha: fq });
      const F = [
        ['max Σ пригодность·y + 10·занятые места', P.ink, 21],
        ['вид ≤ 0,1·T  род ≤ 0,2·T  семейство ≤ 0,3·T', P.ink, 21],
        ['0,15·T ≤ хвойные ≤ 0,40·T', P.ink, 21],
        ['T - число занятых мест, тоже переменная', P.inkSoft, 17],
      ];
      F.forEach(([s, col, sz], i) => G.text(ctx, s, fx + 30, y + 84 + i * 38, { size: sz, weight: 500, family: G.MONO, color: col, p: G.seg(t, SHEET + 1.4 + i * 0.4, 0.8, 'linear') }));
      G.para(ctx, 'Каталог 55 видов. Клён ясенелистный исключён как инвазивный по 369-ПП. Берзарина: 12 видов, индекс Шеннона 2,44.', fx + 30, y + 240 - 20, { size: 18, weight: 400, maxW: 630, lh: 24, color: P.inkSoft, p: G.seg(t, SHEET + 3.0, 1.6, 'linear') });
    }
  }

  FILM.slide({
    id: 'species',
    mode: 'paper',
    dur: DUR,
    tr: { kind: 'morph', dur: 0.4 },
    draw(ctx, t) {
      G.world(ctx, G.CAMS.street, { t: t + 81 });
      G.traffic(ctx, t + 61);
      // группы кустарника вырастают на местах, где квота вида исчерпана
      if (t > QUOTA + EMPTY.length * 0.4 + 1.6) G.shrubsFull(ctx);
      else G.drawPlanShrubs(ctx, (k, c) => lib.seg(t, qAt(c) + 0.9, qAt(c) + 1.6));
      trees(ctx, t);
      ctx.save();
      ctx.globalAlpha *= 1 - G.seg(t, DUR - 1.2, 0.9, 'linear');
      leaves(ctx, t);
      ctx.restore();
      G.caption(ctx, t, QUOTA - 0.2, SHEET - 0.4, 1100, 150, 760, 'Квота вида 10% от занятых мест: лишний экземпляр не ставится. Место, пустое по квотам, занимает группа кустарника 3 × 3 с шагом 1 м. На Берзарина так посажено 636 кустарников.', { size: 23, seed: 13 });
      herbarium(ctx, t);
      G.chapters(ctx, t, 3, { dur: DUR });
      G.chapterTitle(ctx, t, '04 · ВИДЫ', 'Вид подбирается под место', { t0: 0.2, t1: DUR - 0.8 });
    },
  });
})();
