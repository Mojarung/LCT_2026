// 01 титул: Москва рисуется от руки, на ней 19 улиц пилота, одна пульсирует
(function () {
  const FILM = window.FILM, lib = FILM.lib, P = lib.pal, G = FILM.G, E = lib.ease;
  const DUR = 12;

  /** Словесный знак и подзаголовок; второй слайд растворяет их, пока камера летит к картушу. */
  G.titleBlock = (ctx, t, alpha, cam) => {
    if (alpha <= 0) return;
    ctx.save();
    ctx.globalAlpha *= alpha;
    const [bx, by] = G.mapToScreen(cam, G.MB[0], G.MB[1]);
    const lq = G.seg(t, 3.4, 0.5);
    if (lq > 0) {
      lib.inkPath(ctx, [[bx - 14, by - 10], [bx - 90, by - 70], [bx - 200, by - 70]], { width: 2, color: P.annMagenta, seed: 5, taper: 3, alpha: lq });
      G.text(ctx, 'ул. Берзарина', bx - 206, by - 80, { size: 22, weight: 500, family: G.MONO, color: P.annMagenta, align: 'right', p: lq });
    }
    const x = 110;
    G.kicker(ctx, 'ЛЦТ 2026 · КЕЙС ДПиООС МОСКВЫ', x, 300, { color: P.inkSoft, p: G.seg(t, 0.6, 0.8, 'linear') });
    G.text(ctx, 'green', x - 8, 470, { size: 190, weight: 200, color: P.ink, p: G.seg(t, 0.8, 1.4, 'linear'), tracking: 6 });
    lib.ticks(ctx, x, 510, { length: 540 * G.seg(t, 1.2, 1.0), n: 27, len: 9, major: 9, majorLen: 20, color: P.ink, alpha: 0.5, width: 1.5 });
    G.para(ctx, 'Озеленение улиц по нормам и подземным сетям', x, 580, { size: 40, weight: 400, maxW: 600, lh: 52, color: P.ink, p: G.seg(t, 1.8, 1.6, 'linear') });
    G.para(ctx, 'На входе DXF улицы, на выходе план посадок. У каждой посадки и каждого отказа указан пункт нормы.', x, 730, { size: 27, weight: 400, maxW: 560, lh: 38, color: P.inkSoft, p: G.seg(t, 3.0, 2.2, 'linear') });
    ctx.restore();
  };

  FILM.slide({
    id: 'city',
    mode: 'paper',
    dur: DUR,
    tr: { kind: 'fade', dur: 0.6 },
    draw(ctx, t) {
      const cam = G.camLerp(G.CAMS.city, G.CAMS.cityEnd, E.inOutSine(t / DUR));
      G.world(ctx, cam, { t, reveal: G.seg(t, 0.1, 2.6, 'inOutCubic') });
      G.titleBlock(ctx, t, 1, cam);
    },
  });
})();
