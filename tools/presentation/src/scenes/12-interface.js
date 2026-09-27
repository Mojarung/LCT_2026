// 12 интерфейс: камера отъезжает, бумажная улица становится картой прогона; выбор посадки и её норма,
// перенос с живой проверкой, удаление, пересборка DXF, слои
(function () {
  const FILM = window.FILM, lib = FILM.lib, P = lib.pal, G = FILM.G, C = G.C, E = lib.ease;
  const clamp = lib.clamp;
  const UI = G.UI;
  const S = G.street;
  const M = G.M;
  const CAM = { x: 1300, y: 560, zoom: 1 };
  G.CAMS.ui = { x: 1300, y: 560, z: 1 };
  const LEAD = 3.0; // сколько идёт отъезд камеры и полоса прогона до правки

  // полоса хода прогона наверху: этапы бегут до «Готово», потом панель уезжает
  const STAGES = ['Склейка комплекта чертежей', 'Чтение чертежа', 'Разбор подосновы', 'Подоснова для карты', 'Размещение посадок', 'Подбор ассортимента', 'Группы кустарников', 'Индекс качества и ценность посадок', 'Объяснения по нормам', 'Запись DXF', 'Сверка целостности исходника', 'Готово'];
  function progress(ctx, T) {
    const q = G.seg(T, 1.2, 1.8, 'inOutSine');
    const a = G.seg(T, 1.0, 0.3, 'linear') * (1 - G.seg(T, 3.6, 0.4, 'linear'));
    if (a <= 0) return;
    ctx.save();
    ctx.globalAlpha *= a;
    UI.panel(ctx, 560, 30, 800, 110);
    const name = STAGES[Math.min(STAGES.length - 1, Math.floor(q * (STAGES.length - 1) + 0.001))];
    UI.value(ctx, name, 592, 76, { size: 22 });
    G.text(ctx, Math.round(q * 100) + ' %', 1328, 76, { size: 22, weight: 500, family: G.MONO, color: C.bone, align: 'right' });
    ctx.fillStyle = lib.rgba(C.bone, 0.15);
    ctx.fillRect(592, 100, 736, 10);
    ctx.fillStyle = q >= 1 ? C.signal : C.bone;
    ctx.fillRect(592, 100, 736 * q, 10);
    ctx.restore();
  }
  const toScreen = (x, y) => [x - (CAM.x - 960), y - (CAM.y - 540)];

  const TREE = G.TREE3;
  const GONE = G.trees.find((c) => c.row === 'A' && c.x > TREE.x + 200);
  const BAD = [1150, 412], GOOD = [TREE.x + 40, 415];
  // план после правки: для финального слайда, который начинается с этой же карты
  G.EDITED = { TREE, GONE, AT: GOOD };
  const SLOW = 1.2; // правка идёт медленнее, чтобы успевать рассказывать
  const DUR = 24;

  // та же проверка, что на слайде с нормами: первая нарушенная норма или null
  function check(x, y) {
    for (const n of S.nets) {
      const d = G.distPoly(x, y, n.pts) / M - (n.channel ? n.channel / 2 / M : 0);
      if (d < G.RULES[n.key]) return `${n.name} ${G.fmt(d, 1)} < ${G.fmt(G.RULES[n.key], 1)} м`;
    }
    for (const [px, py] of S.poles) {
      const d = Math.hypot(px - x, py - y) / M;
      if (d < G.RULES.pole) return `опора ${G.fmt(d, 1)} < 4,0 м`;
    }
    const dc = Math.abs(y - S.curbA) / M;
    if (dc < G.RULES.curb) return `борт ${G.fmt(dc, 1)} < 2,0 м`;
    return null;
  }

  // положение переносимой посадки
  function treePos(t) {
    if (t < 4.4) return [TREE.x, TREE.y];
    const k = [[4.4, TREE.x, TREE.y], [5.6, BAD[0], BAD[1]], [6.4, BAD[0], BAD[1]], [7.4, GOOD[0], GOOD[1]]];
    return UI.path(k, t);
  }

  function map(ctx, t) {
    const netsOn = G.seg(t, 13.5, 0.4, 'linear');
    lib.camera(ctx, CAM, (g) => {
      UI.street(g);
      UI.nets(g, netsOn);
      UI.plan(g, { skip: TREE, s: (c) => (c === GONE ? 1 - G.seg(t, 9.2, 0.3, 'inBack') : 1) });
      const [x, y] = treePos(t);
      const dragging = t > 4.3 && t < 7.6;
      UI.planting(g, x, y, TREE.sp.r * 0.75, TREE.sp);
      // выбор и вердикт
      if (t > 1.8) {
        const verdict = dragging || (t >= 7.6 && t < 8.6) ? check(x, y) : null;
        const col = !dragging && t < 7.6 ? C.bone : verdict ? P.magenta : C.signal;
        g.save();
        g.strokeStyle = col;
        g.lineWidth = 3;
        g.setLineDash(dragging ? [8, 6] : []);
        g.beginPath();
        g.arc(x, y, TREE.sp.r * 0.75 + 12, 0, Math.PI * 2);
        g.stroke();
        g.restore();
        if (dragging || (t >= 7.6 && t < 8.6)) {
          const txt = verdict ? 'запрещено · ' + verdict : 'допускается';
          const w = G.measure(g, txt, { size: 18, weight: 600, family: G.MONO }) + 22;
          g.fillStyle = col;
          g.beginPath();
          g.roundRect(x - w / 2, y - 92, w, 34, 6);
          g.fill();
          G.text(g, txt, x, y - 69, { size: 18, weight: 600, family: G.MONO, color: C.graphite, align: 'center' });
          G.text(g, 'POST /check', x, y - 104, { size: 15, weight: 500, family: G.MONO, color: C.boneDim, align: 'center' });
        }
      }
      if (t > 8.9 && t < 9.6) {
        const [gx, gy] = [GONE.x, GONE.y];
        g.save();
        g.strokeStyle = C.bone;
        g.lineWidth = 3;
        g.beginPath();
        g.arc(gx, gy, 52, 0, Math.PI * 2);
        g.stroke();
        g.restore();
        g.fillStyle = C.bone;
        g.beginPath();
        g.roundRect(gx - 50, gy - 100, 100, 34, 6);
        g.fill();
        G.text(g, 'Delete', gx, gy - 76, { size: 18, weight: 600, family: G.MONO, color: C.graphite, align: 'center' });
      }
    });
  }

  function left(ctx, t) {
    UI.panel(ctx, 40, 40, 380, 640, { p: G.seg(t, 0.1, 0.5, 'linear') });
    UI.value(ctx, 'berzarina.dxf', 70, 92);
    UI.label(ctx, 'strict · шаг 6 м', 70, 124);
    UI.value(ctx, '608 посадок', 70, 186, { size: 30, weight: 400 });
    UI.label(ctx, '1 734 отклонённых места', 70, 222);
    UI.label(ctx, 'подоснова цела', 70, 262, { color: C.signal });
    UI.label(ctx, '▸ предупреждения', 70, 300);
    ctx.fillStyle = lib.rgba(C.bone, 0.1);
    ctx.fillRect(70, 540, 320, 1);
    UI.check(ctx, 70, 560, 'Переносить и удалять посадки', G.seg(t, 3.3, 0.2, 'linear'));
    const building = t > 10.5 && t < 11.8;
    const built = t >= 11.8;
    UI.button(ctx, 70, 610, 320, 50, building ? 'Пересборка…' : built ? 'DXF собран' : 'Пересобрать DXF', { press: t > 10.5 && t < 10.7 ? 1 : 0, primary: built });
    if (building) {
      ctx.save();
      ctx.strokeStyle = C.bone;
      ctx.lineWidth = 3;
      ctx.beginPath();
      const a = t * 8;
      ctx.arc(110, 635, 11, a, a + 4);
      ctx.stroke();
      ctx.restore();
    }
  }

  function right(ctx, t) {
    UI.panel(ctx, 1500, 40, 380, 1000, { p: G.seg(t, 0.2, 0.5, 'linear') });
    UI.value(ctx, 'Состав плана', 1530, 92);
    UI.field(ctx, 1530, 112, 320, 'Все виды', { select: true });
    G.SPECIES.forEach((sp, i) => {
      const y = 196 + i * 34;
      ctx.fillStyle = sp.fill;
      ctx.beginPath();
      ctx.arc(1542, y - 6, 8, 0, Math.PI * 2);
      ctx.fill();
      G.text(ctx, sp.ru, 1562, y, { size: 17, weight: 400, color: C.bone });
    });
    // карточка выбранной посадки
    const cq = G.seg(t, 2.0, 0.4, 'linear');
    if (cq > 0) {
      ctx.save();
      ctx.globalAlpha *= cq;
      ctx.fillStyle = lib.rgba(C.bone, 0.06);
      ctx.fillRect(1520, 480, 340, 380);
      ctx.restore();
      UI.value(ctx, '№3 · Боярышник обыкновенный', 1536, 520, { size: 19, alpha: cq });
      G.text(ctx, 'Crataegus laevigata', 1536, 548, { size: 17, italic: true, color: C.boneDim, alpha: cq });
      UI.label(ctx, 'ближе всего к норме', 1536, 596, { alpha: cq });
      G.para(ctx, 'бортовой камень 2,00 м при норме 2,00 м', 1536, 626, { size: 19, weight: 500, maxW: 310, lh: 26, color: C.bone, p: G.seg(t, 2.2, 0.6, 'linear') });
      G.para(ctx, 'СП 42.13330.2016, п. 9.6, табл. 9.1; 743-ПП, табл. 3.6.1', 1536, 690, { size: 16, weight: 400, maxW: 310, lh: 22, color: C.boneDim, p: G.seg(t, 2.5, 0.6, 'linear') });
      UI.label(ctx, '▸ остальные нормы', 1536, 760, { alpha: cq });
      UI.label(ctx, 'Чем ценна посадка: вклад', 1536, 806, { alpha: cq, color: C.bone });
      UI.label(ctx, 'в индекс качества, ‰', 1536, 830, { alpha: cq, color: C.bone });
    }
    UI.button(ctx, 1530, 900, 320, 50, 'Скачать DXF', { primary: t >= 11.8 });
    UI.button(ctx, 1530, 962, 320, 50, 'Интерпретации, CSV');
  }

  function controls(ctx, t) {
    const y = 990;
    const items = [['вписать', 110], ['−', 50], ['', 180], ['+', 50], ['по улице', 120], ['обозначения', 150]];
    let x = 440;
    items.forEach(([s, w], i) => {
      if (i === 2) {
        ctx.fillStyle = lib.rgba(C.bone, 0.25);
        ctx.fillRect(x, y + 22, w, 3);
        ctx.fillStyle = C.bone;
        ctx.beginPath();
        ctx.arc(x + w * 0.42, y + 23, 8, 0, Math.PI * 2);
        ctx.fill();
      } else UI.button(ctx, x, y, w, 46, s, { primary: i === 5 && t > 12.6 });
      x += w + 10;
    });
    // панель обозначений со слоями
    const lq = G.seg(t, 12.6, 0.3, 'linear');
    if (lq > 0) {
      UI.panel(ctx, 1030, 690, 440, 270, { p: lq });
      const rows = [['посадки', 1], ['отклонённые места', 1], ['подземные сети, 8 видов', G.seg(t, 13.5, 0.2, 'linear')], ['борта и покрытия, 5', 1], ['здания', 1]];
      rows.forEach(([s, on], i) => UI.check(ctx, 1060, 716 + i * 46, s, on));
    }
  }

  FILM.slide({
    id: 'interface',
    mode: 'ui',
    dur: DUR,
    tr: { kind: 'morph', dur: 0.4 },
    draw(ctx, T) {
      const t = (T - LEAD) / SLOW;
      map(ctx, t);
      // в конце панели уходят, остаётся карта: с неё начинается подъём над городом
      const uiA = 1 - G.seg(T, DUR - 1.8, 0.9, 'linear');
      ctx.save();
      ctx.globalAlpha *= uiA;
      left(ctx, t);
      right(ctx, t);
      controls(ctx, t);
      const [tx, ty] = toScreen(TREE.x, TREE.y);
      const [dx, dy] = toScreen(...treePos(t));
      const [gx, gy] = toScreen(GONE.x, GONE.y);
      const keys = [[0, 1200, 900], [1.4, tx + 6, ty + 6], [2.4, tx + 6, ty + 6], [3.1, 82, 572], [3.6, 82, 572], [4.3, tx + 6, ty + 6]];
      let cx, cy;
      if (t < 4.3) [cx, cy] = UI.path(keys, t);
      else if (t < 7.7) [cx, cy] = [dx + 6, dy + 6];
      else [cx, cy] = UI.path([[7.7, dx + 6, dy + 6], [8.7, gx + 6, gy + 6], [9.6, gx + 6, gy + 6], [10.4, 230, 635], [11.9, 230, 635], [12.5, 1075, 1013], [12.8, 1075, 1013], [13.4, 1072, 820], [16, 1072, 820]], t);
      let click = 0;
      for (const c of [1.8, 3.3, 4.3, 8.9, 10.5, 12.6, 13.5]) if (t > c && t < c + 0.5) click = (t - c) / 0.5;
      if (t > 0.2) UI.cursor(ctx, cx, cy, click);
      G.para(ctx, 'Клик по посадке показывает вид и норму с наименьшим запасом. /check даёт вердикт на лету, /edits принимает перенос и удаление, /rebuild пересобирает DXF с той же проверкой. Кадр карты на Камчатской 8 мс вместо 117.', 460, 820, { size: 20, weight: 400, maxW: 520, lh: 28, color: C.boneDim, p: G.seg(t, 1.0, 2.4, 'linear') });
      ctx.restore();
      progress(ctx, T);
      // бумажная улица уходит: тот же план на том же месте становится картой интерфейса
      const pa = 1 - G.seg(T, 0.5, 1.5, 'inOutSine');
      if (pa > 0) {
        ctx.save();
        ctx.globalAlpha *= pa;
        const cam = G.camLerp(G.CAMS.street, G.CAMS.ui, G.seg(T, 0.45, 1.6, 'inOutCubic'));
        G.world(ctx, cam, { t: T + 150 });
        G.applyCam(ctx, cam);
        G.traffic(ctx, T + 19);
        G.shrubsFull(ctx);
        G.drawPlanTrees(ctx, () => 1);
        ctx.restore();
      }
    },
  });
})();
