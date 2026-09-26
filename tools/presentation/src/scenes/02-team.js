// 02 команда: заголовок растворяется, камера подлетает к картушу в углу той же карты, имена вписываются тушью
(function () {
  const FILM = window.FILM, lib = FILM.lib, P = lib.pal, G = FILM.G, E = lib.ease;

  FILM.slide({
    id: 'team',
    mode: 'paper',
    dur: 11,
    tr: { kind: 'morph', dur: 0.4 },
    draw(ctx, t) {
      const cam = G.camPath([[0, G.CAMS.cityEnd], [0.5, G.CAMS.cityEnd], [3.3, G.CAMS.team, 'inOutSine']], t);
      G.world(ctx, cam, { t: t + 12, team: G.seg(t, 2.8, 5.0, 'linear') });
      G.titleBlock(ctx, 12, 1 - G.seg(t, 0.2, 0.9, 'inOutSine'), cam);
    },
  });
})();
