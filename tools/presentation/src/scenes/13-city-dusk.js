// 13 финал: камера уходит от карты интерфейса вверх, над городом вечер, 19 улиц пилота загораются
(function () {
  const FILM = window.FILM, lib = FILM.lib, P = lib.pal, G = FILM.G, C = G.C, E = lib.ease;
  const clamp = lib.clamp;
  const UP = [0.6, 6.4];
  const DUR = 17;
  // деревья после правки в интерфейсе: одно перенесено, одно удалено
  function editedTrees(c) {
    const E2 = G.EDITED;
    for (const tr of G.trees) {
      if (tr === E2.GONE) continue;
      const [x, y] = tr === E2.TREE ? E2.AT : [tr.x, tr.y];
      G.tree(c, x, y, tr.sp.r, { kind: tr.sp.kind, fill: tr.sp.fill, deep: tr.sp.deep, seed: tr.id * 31 });
    }
  }
  const CITY = G.mapCam(1000, 560, 1.05);

  FILM.slide({
    id: 'city-dusk',
    mode: 'paper',
    dur: DUR,
    tr: { kind: 'morph', dur: 0.4 },
    draw(ctx, t) {
      const cam = G.camPath([[0, G.CAMS.ui], [UP[0], G.CAMS.ui], [UP[1], CITY, 'inOutSine']], t);
      const dusk = G.seg(t, 0.4, 2.6, 'inOutSine');
      const m = cam.z * G.K;
      // карта темнеет своей палитрой, квартал и улица накладкой
      G.world(ctx, cam, { t: t + 160, team: 1, dusk, tint: dusk, bloom: G.seg(t, 6.0, 3.6, 'linear'), plan: (c) => {
        G.shrubsFull(c);
        editedTrees(c);
      } });
      const ov = dusk;
      if (ov > 0) {
        // фонари: тёплые точки на тёмной улице
        if (cam.z > 0.05) {
          ctx.save();
          G.applyCam(ctx, cam);
          for (const [x, y] of G.street.poles) lib.glowDot(ctx, x, y, 8, { color: '#FFE3A3', rays: 0, glow: 9, intensity: ov * 0.9, seed: x });
          ctx.restore();
        }
      }
      // первые кадры: карта интерфейса растворяется в бумажной улице
      const ui = 1 - G.seg(t, 0, 0.6, 'linear');
      if (ui > 0) {
        ctx.save();
        ctx.globalAlpha *= ui;
        ctx.fillStyle = C.graphite;
        ctx.fillRect(0, 0, 1920, 1080);
        lib.camera(ctx, { x: 1300, y: 560, zoom: 1 }, (g) => {
          G.UI.street(g);
          G.UI.plan(g, { skip: G.EDITED.TREE, s: (c) => (c === G.EDITED.GONE ? 0 : 1) });
          G.UI.planting(g, G.EDITED.AT[0], G.EDITED.AT[1], G.EDITED.TREE.sp.r * 0.75, G.EDITED.TREE.sp);
        });
        ctx.restore();
      }
      if (t < UP[1] - 0.6) return;
      const x = 110, bone = '#EDE6F6';
      G.text(ctx, 'green', x - 8, 330, { size: 170, weight: 200, color: bone, p: G.seg(t, UP[1] - 0.4, 1.2, 'linear'), tracking: 6 });
      lib.ticks(ctx, x, 366, { length: 500 * G.seg(t, UP[1], 1.0), n: 25, len: 9, major: 5, majorLen: 20, color: bone, alpha: 0.6, width: 1.5 });
      G.para(ctx, '18 улиц пилота из 19, 33 757 посадок. Исходный чертёж цел на каждой.', x, 440, { size: 32, weight: 400, maxW: 640, lh: 44, color: bone, p: G.seg(t, UP[1] + 0.8, 1.2, 'linear') });
      G.para(ctx, 'docker compose up --build · Swagger /docs · 2148 тестов', x, 570, { size: 21, weight: 500, family: G.MONO, maxW: 700, lh: 30, color: '#C8C1EF', p: G.seg(t, UP[1] + 1.8, 1.0, 'linear') });
      G.kicker(ctx, 'ДАЛЬШЕ', x, 660, { color: '#C8C1EF', p: G.seg(t, UP[1] + 2.6, 0.5, 'linear') });
      ['кустарниковый ярус под кроной аллеи', 'улучшение раскладки в продукт: индекс рос в 8 сценах из 9', 'CP-SAT для аллеи и C-расширения ezdxf', 'визуализация участка по готовому плану'].forEach((s, i) =>
        G.text(ctx, '· ' + s, x, 706 + i * 36, { size: 22, weight: 400, color: bone, p: G.seg(t, UP[1] + 2.8 + i * 0.3, 0.6, 'linear') }));
      G.text(ctx, 'github.com/Mojarung/LCT_2026', x, 900, { size: 22, weight: 500, family: G.MONO, color: '#C8C1EF', p: G.seg(t, UP[1] + 4.2, 0.8, 'linear') });
    },
  });
})();
