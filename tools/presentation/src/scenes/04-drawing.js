// 03 чтение: камера спускается с карты в улицу, чертёж раскладывается на слои и собирается обратно
(function () {
  const FILM = window.FILM, lib = FILM.lib, P = lib.pal, G = FILM.G, C = G.C, E = lib.ease;
  const clamp = lib.clamp;

  const DUR = 23, DIVE = 6.0, OPEN = [6.6, 8.2], CLOSE = [14.6, 15.8];
  const LAYERS = [
    ['nets', 'подземные сети', (g) => G.drawNetsBlue(g, { labels: false })],
    ['road', 'проезжая часть и борта', (g) => G.drawSurface(g, { part: 'road' })],
    ['lawns', 'газоны', (g) => G.drawSurface(g, { part: 'lawns' })],
    ['walks', 'тротуары и покрытия', (g) => G.drawSurface(g, { part: 'walks' })],
    ['buildings', 'здания', (g) => G.drawSurface(g, { part: 'buildings' })],
  ];

  // изометрия: поворот, сжатие по высоте, общий масштаб; слой i поднят над нижним
  const TH = -0.35, SQ = 0.5, KK = 0.48, CX = 1100, CY = 610, GAP = 118;
  function layerMatrix(q, i) {
    const c = Math.cos(TH), s = Math.sin(TH);
    const L = [KK * c, -KK * s, KK * SQ * s, KK * SQ * c];
    const A = [lib.lerp(1, L[0], q), lib.lerp(0, L[1], q), lib.lerp(0, L[2], q), lib.lerp(1, L[3], q)];
    const off = -(i - (LAYERS.length - 1) / 2) * GAP * q;
    const cx = lib.lerp(960, CX, q), cy = lib.lerp(540, CY, q);
    // x' = cx + A0 (x - 960) + A1 (y - 540); y' = cy + A2 (x - 960) + A3 (y - 540) + off
    return [A[0], A[2], A[1], A[3], cx - A[0] * 960 - A[1] * 540, cy - A[2] * 960 - A[3] * 540 + off];
  }
  const apply = (M, x, y) => [M[0] * x + M[2] * y + M[4], M[1] * x + M[3] * y + M[5]];

  function exploded(ctx, t, q) {
    const bob = Math.sin(t * 1.3);
    LAYERS.forEach(([key, name, fn], i) => {
      const M = layerMatrix(q, i);
      M[5] += bob * 6 * q * (i - 2);
      ctx.save();
      ctx.transform(...M);
      // лист слоя: полупрозрачная бумага с рамкой
      ctx.fillStyle = lib.rgba(P.paper, 0.72 * q);
      ctx.fillRect(0, 0, 1920, 1080);
      ctx.drawImage(G.cachedCanvas('part-' + key, fn), 0, 0, 1920, 1080);
      ctx.strokeStyle = lib.rgba(P.ink, 0.8 * q);
      ctx.lineWidth = 3 / KK;
      ctx.strokeRect(0, 0, 1920, 1080);
      ctx.restore();
      // подпись слоя справа, с выноской
      const la = G.seg(t, OPEN[1] - 0.2 + i * 0.22, 0.4, 'linear') * (1 - G.seg(t, CLOSE[0] - 0.3, 0.3, 'linear'));
      if (la > 0) {
        const [ax, ay] = apply(M, 1920, 540);
        lib.inkPath(ctx, [[ax + 6, ay], [ax + 60, ay - 20]], { width: 1.8, color: P.annBlue, seed: i + 3, taper: 2, alpha: la });
        G.text(ctx, name, ax + 68, ay - 14, { size: 21, weight: 500, family: G.MONO, color: i === 0 ? P.annMagenta : P.ink, p: la });
      }
    });
  }

  function desk(ctx) {
    // стол под листами: миллиметровка
    ctx.fillStyle = '#EDE6D3';
    ctx.fillRect(0, 0, 1920, 1080);
    ctx.save();
    ctx.strokeStyle = lib.rgba(P.annBlue, 0.12);
    ctx.lineWidth = 1;
    ctx.beginPath();
    for (let x = 0; x <= 1920; x += 24) { ctx.moveTo(x, 0); ctx.lineTo(x, 1080); }
    for (let y = 0; y <= 1080; y += 24) { ctx.moveTo(0, y); ctx.lineTo(1920, y); }
    ctx.stroke();
    ctx.strokeStyle = lib.rgba(P.annBlue, 0.22);
    ctx.beginPath();
    for (let x = 0; x <= 1920; x += 120) { ctx.moveTo(x, 0); ctx.lineTo(x, 1080); }
    for (let y = 0; y <= 1080; y += 120) { ctx.moveTo(0, y); ctx.lineTo(1920, y); }
    ctx.stroke();
    ctx.restore();
  }

  FILM.slide({
    id: 'drawing',
    mode: 'paper',
    dur: DUR,
    tr: { kind: 'lens', dur: 1.5, x: 960, y: 540, ring: P.lavender },
    draw(ctx, t) {
      const cam = G.camPath([[0, G.CAMS.mark], [0.6, G.CAMS.mark], [DIVE, G.CAMS.street, 'inOutSine']], t);
      const q = G.seg(t, OPEN[0], OPEN[1] - OPEN[0], 'inOutCubic') * (1 - G.seg(t, CLOSE[0], CLOSE[1] - CLOSE[0], 'inOutCubic'));
      // улица и разложенные листы сменяют друг друга растворением, без скачка
      const flat = 1 - lib.clamp(q / 0.18);
      if (flat < 1) {
        desk(ctx);
        exploded(ctx, t, q);
      }
      if (flat > 0) {
        ctx.save();
        ctx.globalAlpha *= flat;
        G.world(ctx, cam, { t: t + 23, team: 1 });
        if (cam.z > 0.2) {
          G.applyCam(ctx, cam);
          G.traffic(ctx, t);
        }
        ctx.restore();
      }
      G.chapters(ctx, t, 0, { dur: DUR });
      if (t < DIVE) return;
      G.chapterTitle(ctx, t, '01 · ЧТЕНИЕ', 'Чертёж раскладывается на слои', { t0: DIVE + 0.1, t1: DUR - 0.8 });
      G.caption(ctx, t, DIVE + 0.5, DUR - 0.9, 60, 170, 560, 'Берзарина: 206 860 объектов. Чтение с ремонтом строк LibreDWG заняло 55 с.', { seed: 3 });
      G.caption(ctx, t, 9.8, DUR - 0.9, 60, 400, 560, '66 правил layer_map.yaml раскладывают слои по 28 классам. Неизвестный объект останавливает прогон до уточнения.', { seed: 5 });
      G.caption(ctx, t, 16.2, DUR - 0.9, 60, 690, 560, 'Единицы берутся из . REGION без ACIS и XCLIP останавливают расчёт с причиной в input_read.json.', { seed: 7 });
    },
  });
})();
