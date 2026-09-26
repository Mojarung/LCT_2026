// 08 объяснение: камера ныряет в одно дерево; крупный план посадки и отказа, тексты дословно из interpretations.csv
(function () {
  const FILM = window.FILM, lib = FILM.lib, P = lib.pal, G = FILM.G, C = G.C, E = lib.ease;
  const clamp = lib.clamp;
  const K = 90; // пикселей в метре на крупном плане
  const TX = 540, TY = 600;
  const SWITCH = 12.5; // в локальном времени крупного плана
  const IN = 2.6, OUT = 24.4, DUR = 27;

  const PLANT = [
    ['Посадка №3, Боярышник обыкновенный (Crataegus laevigata), аллея вдоль борта: посадка допускается.', P.ink, 500],
    ['до бортового камня 2.00 м >= 2.00 м (R-CURB-TREE-001: СП 42.13330.2016, п. 9.6, табл. 9.1; 743-ПП, п. 3.6.3, табл. 3.6.1; 623-ПП (МГСН 1.02-02), п. 4.2.4)', P.inkSoft, 400],
    ['до канализации до наружной стенки 2.44 м >= 1.50 м (R-SEWER-TREE-001: …)', P.inkSoft, 400],
    ['до края тротуара 2.00 м >= 0.70 м (R-SWALK-TREE-001: …); до границы покрытия 2.11 м >= 0.70 м (R-PAVE-TREE-001: …)', P.inkSoft, 400],
    ['Вид: Боярышник обыкновенный (74%, рядовая посадка одного вида) рекомендован для категории «улицы и дороги» (МГСН 1.02-02, прил. В, табл. В.6) … Альтернативы: Клён Гиннала 45%, Сосна горная 42%, Черёмуха виргинская 38%.', P.ink, 400],
  ];
  const REJECT = [
    ['Отказ №1: посадка запрещена.', P.annMagenta, 500],
    ['Причины: до наружной стены здания 3.37 м < 5.00 м (R-BLD-TREE-001: СП 42.13330.2016, п. 9.6, табл. 9.1: наружная стена здания и сооружения; 743-ПП, п. 3.6.3, табл. 3.6.1; 623-ПП (МГСН 1.02-02), п. 4.2.4)', P.ink, 400],
    ['…', P.inkSoft, 400],
    ['до силового кабеля до наружной стенки 1.84 м < 2.00 м (R-POWER-TREE-001: …)', P.ink, 400],
  ];

  function ground(ctx, o) {
    // тротуар сверху, газон, борт, проезжая часть снизу
    const walkY = TY - 2 * K, curbY = TY + 2 * K;
    ctx.fillStyle = C.tile;
    ctx.fillRect(-20, 0, 1120, walkY);
    ctx.strokeStyle = lib.rgba(P.inkFaint, 0.25);
    ctx.lineWidth = 1.2;
    ctx.beginPath();
    for (let x = 0; x < 1100; x += 60) { ctx.moveTo(x, 0); ctx.lineTo(x, walkY); }
    for (let y = walkY - 30; y > 0; y -= 30) { ctx.moveTo(-20, y); ctx.lineTo(1100, y); }
    ctx.stroke();
    ctx.fillStyle = C.lawn;
    ctx.fillRect(-20, walkY, 1120, curbY - walkY);
    lib.hatch(ctx, lib.rectPts(-20, walkY + 6, 1120, curbY - walkY - 12, 40), { angle: -1.2, spacing: 13, length: [8, 18], gap: [8, 20], width: 1.5, color: C.lawnDeep, alpha: 0.8, seed: 3 });
    ctx.fillStyle = C.asphalt;
    ctx.fillRect(-20, curbY, 1120, 1080 - curbY);
    lib.stipple(ctx, lib.rectPts(-20, curbY + 10, 1120, 1080 - curbY, 60), { spacing: 11, r: [0.8, 1.6], color: P.inkSoft, alpha: 0.3, seed: 8, density: 0.5 });
    lib.inkLine(ctx, -20, curbY, 1100, curbY, { width: 5, seed: 11 });
    lib.inkLine(ctx, -20, curbY + 10, 1100, curbY + 10, { width: 1.8, seed: 12, alpha: 0.6 });
    lib.inkLine(ctx, -20, walkY, 1100, walkY, { width: 2.6, seed: 13 });
    if (o.paving) {
      // въезд с покрытием слева
      const px = TX - 2.11 * K;
      ctx.fillStyle = C.tile;
      ctx.fillRect(px - 150, walkY, 150, curbY - walkY);
      lib.inkLine(ctx, px, walkY, px, curbY, { width: 2.6, seed: 14 });
      lib.inkLine(ctx, px - 150, walkY, px - 150, curbY, { width: 2.6, seed: 15 });
    }
    if (o.building) {
      const by = TY - 3.37 * K;
      ctx.fillStyle = C.roof;
      ctx.fillRect(-20, -20, 1120, by + 20);
      lib.hatch(ctx, lib.rectPts(-20, -20, 1120, by + 20, 40), { spacing: 10, width: 1.4, color: C.roofDeep, alpha: 0.7, seed: 17 });
      lib.inkLine(ctx, -20, by, 1100, by, { width: 5, seed: 16, double: true });
    }
  }

  function dim(ctx, x1, y1, x2, y2, label, color, q, lx, ly) {
    if (q <= 0) return;
    lib.bracket(ctx, x1, y1, x2, y2, { color, alpha: 1, width: 2.5, p: q, cap: 18 });
    const a = clamp((q - 0.5) * 2);
    if (a <= 0) return;
    const w = G.measure(ctx, label, { size: 22, weight: 500, family: G.MONO }) + 20;
    const x = lx != null ? lx : (x1 + x2) / 2 + 16;
    const y = ly != null ? ly : (y1 + y2) / 2;
    ctx.save();
    ctx.globalAlpha *= a;
    ctx.fillStyle = color;
    ctx.fillRect(x, y - 17, w, 34);
    ctx.restore();
    G.text(ctx, label, x + 10, y + 8, { size: 22, weight: 500, family: G.MONO, color: P.white, alpha: a });
  }

  function plantScene(ctx, t) {
    G.cached(ctx, 'closeup-plant', (g) => {
      ground(g, { paving: true });
      G.tree(g, TX, TY, 1.6 * K, { fill: '#B9C98A', deep: '#7D9152', seed: 3 });
    });
    // канализация под проезжей частью: рентгеновская вставка
    const sy = TY + 2.44 * K;
    ctx.save();
    ctx.setLineDash([14, 10]);
    ctx.strokeStyle = P.teal;
    ctx.lineWidth = 4;
    ctx.beginPath();
    ctx.moveTo(-20, sy);
    ctx.lineTo(1100, sy);
    ctx.stroke();
    ctx.restore();
    G.text(ctx, 'канализация', 40, sy + 34, { size: 20, weight: 500, family: G.MONO, color: P.tealDeep });
    G.text(ctx, '№3', TX + 1.6 * K + 12, TY - 1.2 * K, { size: 26, weight: 500, family: G.MONO, color: P.ink, alpha: G.seg(t, 0.6, 0.3, 'linear') });
    dim(ctx, TX + 40, TY, TX + 40, TY + 2 * K, 'борт 2,00 ≥ 2,00', P.annBlue, G.seg(t, 1.2, 0.5), TX + 170, TY + 120);
    dim(ctx, TX + 110, TY, TX + 110, sy, 'канализация 2,44 ≥ 1,50', P.teal, G.seg(t, 2.2, 0.5), TX + 170, TY + 170);
    dim(ctx, TX - 40, TY, TX - 40, TY - 2 * K, 'тротуар 2,00 ≥ 0,70', P.annBlue, G.seg(t, 3.2, 0.5), TX - 20, TY - 2 * K - 34);
    dim(ctx, TX, TY + 60, TX - 2.11 * K, TY + 60, 'покрытие 2,11 ≥ 0,70', P.annYellow, G.seg(t, 4.2, 0.5), 30, TY + 110);
    // норма пунктиром поверх: где проходит граница допустимого
    lib.guideCircle(ctx, TX, TY, 2 * K, { color: P.annBlue, alpha: 0.6 * G.seg(t, 1.2, 0.6), dash: [6, 6], width: 2 });
  }

  function rejectScene(ctx, t) {
    G.cached(ctx, 'closeup-reject', (g) => ground(g, { building: true }));
    const cy = TY + 1.84 * K;
    ctx.save();
    ctx.setLineDash([14, 10]);
    ctx.strokeStyle = P.annMagenta;
    ctx.lineWidth = 4;
    ctx.beginPath();
    ctx.moveTo(-20, cy);
    ctx.lineTo(1100, cy);
    ctx.stroke();
    ctx.restore();
    G.text(ctx, 'силовой кабель', 60, cy - 16, { size: 20, weight: 500, family: G.MONO, color: P.annMagenta });
    // тень несостоявшегося дерева и крестик
    lib.guideCircle(ctx, TX, TY, 1.6 * K, { color: P.ink, alpha: 0.5, dash: [5, 7], width: 2 });
    G.cross(ctx, TX, TY, 34, { p: G.seg(t, SWITCH + 0.3, 0.3, 'linear'), width: 6 });
    // нормы: 5 м до стены, 2 м до кабеля
    lib.guideCircle(ctx, TX, TY, 5 * K, { color: P.annMagenta, alpha: 0.5, dash: [8, 8], width: 2, p: G.seg(t, SWITCH + 0.6, 0.8) });
    dim(ctx, TX + 60, TY, TX + 60, TY - 3.37 * K, 'стена 3,37 < 5,00', P.annMagenta, G.seg(t, SWITCH + 0.9, 0.5), TX + 80, TY - 150);
    dim(ctx, TX - 70, TY, TX - 70, cy, 'кабель 1,84 < 2,00', P.annMagenta, G.seg(t, SWITCH + 1.6, 0.5), TX - 330, TY + 60);
    G.ring(ctx, TX, TY, 70, t, SWITCH + 0.35, { color: P.annMagenta, dur: 0.6 });
  }

  function card(ctx, t, lines, t0, alpha) {
    const x = 1110, w = 770;
    ctx.save();
    ctx.globalAlpha *= alpha;
    G.card(ctx, x, 150, w, 540, { p: G.seg(t, t0, 0.4), seed: 31 });
    let y = 214;
    lines.forEach(([s, col, wt], i) => {
      const h = G.para(ctx, s, x + 36, y, { size: i === 0 ? 28 : 23, weight: wt, maxW: w - 72, lh: i === 0 ? 36 : 31, color: col, p: G.seg(t, t0 + 0.4 + i * 1.0, 1.3, 'linear') });
      y += h + 16;
    });
    ctx.restore();
  }

  function closeup(ctx, t) {
    const sw = G.seg(t, SWITCH, 0.5, 'inOutCubic');
    ctx.save();
    ctx.beginPath();
    ctx.rect(0, 0, 1080, 1080);
    ctx.clip();
    if (sw < 1) plantScene(ctx, t);
    if (sw > 0) {
      ctx.save();
      ctx.beginPath();
      ctx.rect(0, 0, 1080 * sw, 1080);
      ctx.clip();
      rejectScene(ctx, t);
      ctx.restore();
      if (sw < 1) lib.inkLine(ctx, 1080 * sw, 0, 1080 * sw, 1080, { width: 4, color: P.annMagenta, boil: false });
    }
    ctx.restore();
    lib.inkLine(ctx, 1080, 0, 1080, 1080, { width: 3, seed: 40 });
    lib.stripes(ctx, { colors: [P.stripeCream, P.stripeApricot], bounds: [1083, 0, 837, 1080], offset: t * 10 });
    // карточка посадки гаснет, карточка отказа проявляется поверх: без кадра пустоты
    if (t < SWITCH + 0.4) card(ctx, t, PLANT, 0.3, 1 - G.seg(t, SWITCH, 0.4, 'linear'));
    if (t > SWITCH) card(ctx, t, REJECT, SWITCH, G.seg(t, SWITCH, 0.4, 'linear'));
    G.text(ctx, 'interpretations.csv', 1146, 730, { size: 22, weight: 600, family: G.MONO, color: P.ink, p: G.seg(t, 6.0, 0.6, 'linear') });
    ['kind · number · species_ru · x · y · verdict', 'rule_id · measured_m · threshold_m · act_id', 'clause · citation_status · quote · value · …'].forEach((s, i) => G.text(ctx, s, 1146, 770 + i * 30, { size: 19, weight: 400, family: G.MONO, color: P.inkSoft, p: G.seg(t, 6.3 + i * 0.4, 0.8, 'linear') }));
    G.para(ctx, 'В DXF у каждого блока атрибуты NUM, SPECIES, NPA и XDATA LCT_GREEN. Текст собирают шаблоны из трассы правил, без LLM.', 1146, 900, { size: 22, weight: 400, maxW: 720, lh: 30, color: P.inkSoft, p: G.seg(t, 7.6, 1.8, 'linear') });
  }

  function street(ctx, t, cam) {
    G.world(ctx, cam, { t: t + 100 });
    ctx.save();
    G.applyCam(ctx, cam);
    G.zoomNow = cam.z;
    G.traffic(ctx, t + 81);
    G.shrubsFull(ctx);
    G.drawPlanTrees(ctx, () => 1);
    G.zoomNow = 1;
    ctx.restore();
  }

  FILM.slide({
    id: 'explain',
    mode: 'paper',
    dur: DUR,
    tr: { kind: 'morph', dur: 0.4 },
    draw(ctx, t) {
      const camIn = G.camPath([[0, G.CAMS.street], [0.5, G.CAMS.street], [IN, G.CAMS.tree, 'inOutSine']], t);
      const camOut = G.camPath([[OUT + 0.3, G.CAMS.tree], [DUR - 0.2, G.CAMS.street, 'inOutSine']], t);
      const inA = G.seg(t, IN - 0.4, 0.5, 'linear');
      const outA = G.seg(t, OUT, 0.4, 'linear');
      if (inA < 1) street(ctx, t, camIn);
      if (outA > 0) street(ctx, t, camOut);
      const cq = inA * (1 - outA);
      if (cq > 0) {
        ctx.save();
        ctx.globalAlpha *= cq;
        closeup(ctx, t - IN);
        ctx.restore();
      }
      G.chapters(ctx, t, 4, { dur: DUR });
      if (cq > 0.5) G.chapterTitle(ctx, t, '05 · ОБЪЯСНЕНИЕ', 'Каждое решение с пунктом нормы', { t0: IN, t1: OUT - 0.5 });
    },
  });
})();
