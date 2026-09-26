/*
 * player.js : показ слайдов.
 *
 *   сами по себе     слайды идут подряд до последнего и замирают на нём
 *   → ← PgDn PgUp   листать; после ручного шага слайд доигрывает анимацию и ждёт
 *   клик            следующий слайд
 *   пробел          пауза
 *   Enter           снова автопоказ с текущего слайда
 *   Home / End      к первому / последнему
 *   F               полный экран
 *   M               звук
 *   ?s=N&t=сек&still=1   открыть слайд N на секунде t и заморозить кадр (для снимков)
 */
(function () {
  'use strict';

  const FILM = window.FILM;
  const lib = FILM.lib;
  const P = lib.pal;
  const W = FILM.W;
  const H = FILM.H;
  const slides = FILM.SLIDES;
  const N = slides.length;
  const params = new URLSearchParams(location.search);
  const EPS = 1e-6;
  const clamp01 = (v) => (v < 0 ? 0 : v > 1 ? 1 : v);

  const canvas = document.getElementById('stage');
  let ctx = canvas.getContext('2d', { alpha: false });
  const layerA = FILM.makeCanvas(2, 2);
  const layerB = FILM.makeCanvas(2, 2);
  const ctxA = layerA.getContext('2d', { alpha: false });
  const ctxB = layerB.getContext('2d', { alpha: false });

  // ---------------------------------------------------------------------------
  // Размер и качество
  // ---------------------------------------------------------------------------

  const MAX_PX = Number(params.get('px')) || 2560;
  let quality = 1;
  function resize() {
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    const cssW = Math.min(vw, (vh * 16) / 9);
    const cssH = (cssW * 9) / 16;
    canvas.style.width = cssW + 'px';
    canvas.style.height = cssH + 'px';
    const dpr = window.devicePixelRatio || 1;
    const pw = Math.max(640, Math.min(MAX_PX, Math.round(cssW * dpr * quality)));
    const ph = Math.round((pw * 9) / 16);
    for (const c of [canvas, layerA, layerB]) {
      c.width = pw;
      c.height = ph;
    }
    ctx = canvas.getContext('2d', { alpha: false });
    FILM.S = pw / W;
  }
  window.addEventListener('resize', resize);
  resize();

  function base(c) {
    c.setTransform(c.canvas.width / W, 0, 0, c.canvas.height / H, 0, 0);
  }

  function resetCtx(c, clear) {
    if (clear && typeof c.reset === 'function') c.reset();
    else {
      for (let i = 0; i < 32; i++) c.restore();
      c.setTransform(1, 0, 0, 1, 0, 0);
      c.globalAlpha = 1;
      c.globalCompositeOperation = 'source-over';
      c.setLineDash([]);
    }
    c.imageSmoothingEnabled = true;
    c.imageSmoothingQuality = 'high';
  }

  // ---------------------------------------------------------------------------
  // Кадр одного слайда
  // ---------------------------------------------------------------------------

  let clock = 0; // общее время показа: от него кипят линии
  function drawSlide(c, i, t) {
    const s = slides[i];
    resetCtx(c, true);
    c.fillStyle = s.mode === 'blue' ? P.navy : s.mode === 'ui' ? FILM.G.C.graphite : P.paper;
    c.fillRect(0, 0, c.canvas.width, c.canvas.height);
    base(c);
    FILM.frameT = clock;
    const info = { i, dur: s.dur, p: clamp01(t / s.dur), T: clock, W, H, lib, mode: s.mode, S: FILM.S };
    try {
      if (FILM.G) {
        FILM.G.sunA = 0.9;
        FILM.G.zoomNow = 1;
      }
      c.save();
      s.draw(c, t, info);
      c.restore();
    } catch (e) {
      console.error('slide ' + s.id, e);
      resetCtx(c);
      base(c);
      c.fillStyle = '#5a1010';
      c.fillRect(0, 0, W, H);
      c.fillStyle = '#fff';
      c.font = '32px monospace';
      c.fillText(s.id + ': ' + (e && e.message), 60, 120);
    }
    resetCtx(c);
  }

  // ---------------------------------------------------------------------------
  // Переходы: A уходит, B приходит, p от 0 до 1
  // ---------------------------------------------------------------------------

  const E = lib.ease;
  function composite(tr, A, B, p, dir, fromMode) {
    resetCtx(ctx);
    const w = ctx.canvas.width;
    const h = ctx.canvas.height;
    const S = w / W;
    const kind = tr.kind || 'fade';
    const x = (tr.x != null ? tr.x : W / 2) * S;
    const y = (tr.y != null ? tr.y : H / 2) * S;
    if (kind === 'cut') {
      ctx.drawImage(B, 0, 0);
      return;
    }
    if (kind === 'fade' || kind === 'morph') {
      const e = E.inOutSine(p);
      ctx.drawImage(A, 0, 0);
      ctx.globalAlpha = e;
      ctx.drawImage(B, 0, 0);
      return;
    }
    if (kind === 'lens') {
      // рентгеновская линза: B проявляется в растущем круге, по краю идёт кольцо с делениями
      const e = E.inOutSine(p);
      const R = Math.hypot(Math.max(x, w - x), Math.max(y, h - y)) * 1.02;
      const r = Math.max(0.5, e * R);
      ctx.drawImage(A, 0, 0);
      ctx.save();
      ctx.beginPath();
      ctx.arc(x, y, r, 0, Math.PI * 2);
      ctx.clip();
      const k = 1.08 - 0.08 * e; // внутри линзы лёгкое увеличение
      ctx.translate(x, y);
      ctx.scale(k, k);
      ctx.translate(-x, -y);
      ctx.drawImage(B, 0, 0);
      ctx.restore();
      ringEdge(x, y, r, S, p, tr.ring || (fromMode === 'blue' ? P.lavender : P.ink));
      return;
    }
    if (kind === 'scan') {
      // диагональная развёртка по углу полос
      const e = E.inOutSine(p);
      const a = tr.angle != null ? tr.angle : -0.52;
      const nx = -Math.sin(a), ny = Math.cos(a);
      const L = (Math.abs(nx) * w + Math.abs(ny) * h) / 2 + 80 * S;
      const d = -L + 2 * L * e;
      const cx = w / 2, cy = h / 2;
      const ux = Math.cos(a), uy = Math.sin(a);
      const far = Math.hypot(w, h);
      ctx.drawImage(A, 0, 0);
      ctx.save();
      ctx.beginPath();
      const px0 = cx + nx * d, py0 = cy + ny * d;
      ctx.moveTo(px0 - ux * far, py0 - uy * far);
      ctx.lineTo(px0 + ux * far, py0 + uy * far);
      ctx.lineTo(px0 + ux * far - nx * far * 2, py0 + uy * far - ny * far * 2);
      ctx.lineTo(px0 - ux * far - nx * far * 2, py0 - uy * far - ny * far * 2);
      ctx.closePath();
      ctx.clip();
      ctx.drawImage(B, 0, 0);
      ctx.restore();
      // кромка: двойная линия и штрихи вдоль неё
      ctx.save();
      ctx.strokeStyle = tr.ring || P.annYellow;
      ctx.lineWidth = 3 * S;
      ctx.beginPath();
      ctx.moveTo(px0 - ux * far, py0 - uy * far);
      ctx.lineTo(px0 + ux * far, py0 + uy * far);
      ctx.stroke();
      ctx.globalAlpha = 0.45;
      ctx.lineWidth = 1.5 * S;
      ctx.beginPath();
      ctx.moveTo(px0 - ux * far + nx * 9 * S, py0 - uy * far + ny * 9 * S);
      ctx.lineTo(px0 + ux * far + nx * 9 * S, py0 + uy * far + ny * 9 * S);
      ctx.stroke();
      ctx.restore();
      return;
    }
    if (kind === 'push') {
      // бумага едет: соседний лист приходит сбоку, как продолжение одного чертежа
      const e = E.inOutCubic(p);
      const sgn = dir < 0 ? -1 : 1;
      const vertical = tr.axis === 'y';
      const dx = vertical ? 0 : -sgn * w * e;
      const dy = vertical ? -sgn * h * e : 0;
      ctx.drawImage(A, dx, dy);
      ctx.drawImage(B, dx + (vertical ? 0 : sgn * w), dy + (vertical ? sgn * h : 0));
      ctx.save();
      ctx.globalAlpha = Math.sin(Math.PI * p) * 0.5;
      ctx.fillStyle = P.ink;
      if (vertical) ctx.fillRect(0, dy + sgn * h - 2 * S, w, 4 * S);
      else ctx.fillRect(dx + (sgn > 0 ? w : 0) - 2 * S, 0, 4 * S, h);
      ctx.restore();
      return;
    }
    if (kind === 'zoom') {
      // наезд в точку: A растёт и тает, B собирается из той же точки
      const e = E.inOutCubic(p);
      const zA = 1 + 5 * E.inQuart(p);
      ctx.save();
      ctx.translate(x, y);
      const zB = 0.55 + 0.45 * E.outCubic(p);
      ctx.scale(zB, zB);
      ctx.translate(-x, -y);
      ctx.drawImage(B, 0, 0);
      ctx.restore();
      ctx.save();
      ctx.globalAlpha = 1 - clamp01((e - 0.25) / 0.6);
      ctx.translate(x, y);
      ctx.scale(zA, zA);
      ctx.translate(-x, -y);
      ctx.drawImage(A, 0, 0);
      ctx.restore();
      return;
    }
    if (kind === 'ink') {
      // B проступает кляксами, как тушь, растекающаяся по бумаге
      const e = E.inOutCubic(p);
      ctx.drawImage(A, 0, 0);
      ctx.save();
      ctx.beginPath();
      const r = lib.rng('ink' + (tr.seed || 1));
      for (let k = 0; k < 26; k++) {
        const bx = r() * w, by = r() * h;
        const delay = r() * 0.45;
        const q = clamp01((e - delay) / (1 - delay));
        const rad = E.outCubic(q) * Math.hypot(w, h) * (0.18 + r() * 0.22);
        if (rad <= 0) continue;
        ctx.moveTo(bx + rad, by);
        const n = 28;
        for (let j = 1; j <= n; j++) {
          const aa = (j / n) * Math.PI * 2;
          const wob = 1 + 0.12 * lib.noise1(j * 0.7 + k * 3.1, 5);
          ctx.lineTo(bx + Math.cos(aa) * rad * wob, by + Math.sin(aa) * rad * wob);
        }
        ctx.closePath();
      }
      ctx.clip();
      ctx.drawImage(B, 0, 0);
      ctx.restore();
      return;
    }
    ctx.drawImage(B, 0, 0);
  }

  function ringEdge(x, y, r, S, p, color) {
    const fade = Math.sin(Math.PI * clamp01(p));
    if (fade <= 0.01) return;
    ctx.save();
    ctx.globalAlpha = fade;
    ctx.strokeStyle = color;
    ctx.lineWidth = 3 * S;
    ctx.beginPath();
    ctx.arc(x, y, r, 0, Math.PI * 2);
    ctx.stroke();
    ctx.globalAlpha = fade * 0.5;
    ctx.lineWidth = 1.5 * S;
    ctx.beginPath();
    ctx.arc(x, y, r + 12 * S, 0, Math.PI * 2);
    ctx.stroke();
    // деления по кольцу, поворачиваются вместе с раскрытием
    ctx.globalAlpha = fade * 0.8;
    ctx.lineWidth = 2 * S;
    ctx.beginPath();
    const n = 72;
    for (let k = 0; k < n; k++) {
      const a = (k / n) * Math.PI * 2 + p * 1.4;
      const L = (k % 6 === 0 ? 22 : 10) * S;
      ctx.moveTo(x + Math.cos(a) * (r + 12 * S), y + Math.sin(a) * (r + 12 * S));
      ctx.lineTo(x + Math.cos(a) * (r + 12 * S + L), y + Math.sin(a) * (r + 12 * S + L));
    }
    ctx.stroke();
    ctx.restore();
  }

  // ---------------------------------------------------------------------------
  // Шкала внизу: деление на каждый слайд, как линейка на чертеже
  // ---------------------------------------------------------------------------

  function hud(mode) {
    resetCtx(ctx);
    base(ctx);
    const col = mode === 'blue' ? P.lavender : mode === 'ui' ? FILM.G.C.boneDim : P.inkSoft;
    const x0 = 60, x1 = W - 60, y = H - 26;
    const seg = (x1 - x0) / N;
    ctx.save();
    ctx.strokeStyle = col;
    ctx.globalAlpha = 0.35;
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.moveTo(x0, y);
    ctx.lineTo(x1, y);
    for (let k = 0; k <= N; k++) {
      ctx.moveTo(x0 + k * seg, y - (k % 5 === 0 ? 12 : 7));
      ctx.lineTo(x0 + k * seg, y);
    }
    ctx.stroke();
    ctx.globalAlpha = 0.9;
    ctx.strokeStyle = mode === 'paper' ? P.annMagenta : P.magenta;
    ctx.lineWidth = 3;
    ctx.beginPath();
    const prog = clamp01(lt / slides[idx].dur);
    ctx.moveTo(x0 + idx * seg, y);
    ctx.lineTo(x0 + (idx + prog) * seg, y);
    ctx.stroke();
    ctx.restore();
    lib.text(ctx, String(idx + 1).padStart(2, '0') + ' / ' + String(N).padStart(2, '0'), x1, y - 14, {
      size: 20, weight: 400, color: col, alpha: 0.6, align: 'right', tracking: 2,
      family: 'ui-monospace, "Cascadia Mono", Consolas, "DejaVu Sans Mono", monospace',
    });
    let status = '';
    if (paused) status = 'пауза';
    else if (!auto) status = 'ручной показ';
    if (status) lib.text(ctx, status, x0, y - 14, { size: 20, weight: 400, color: col, alpha: 0.6, tracking: 2 });
    const hintA = 1 - clamp01((clock - 5) / 1.5);
    if (hintA > 0) {
      lib.text(ctx, '← → листать   пробел пауза   F полный экран   M звук', W / 2, y - 14, {
        size: 20, weight: 400, color: col, alpha: 0.55 * hintA, align: 'center', tracking: 1,
      });
    }
  }

  // ---------------------------------------------------------------------------
  // Состояние показа
  // ---------------------------------------------------------------------------

  let idx = Math.max(0, Math.min(N - 1, (Number(params.get('s')) || 1) - 1));
  let lt = Number(params.get('t')) || 0;
  let auto = !params.has('s');
  let paused = params.get('still') === '1';
  let trans = null; // { from, fromLt, t, tr, dir }
  if (params.has('tr') && idx > 0) {
    // кадр перехода для снимков: ?s=N&tr=доля
    const tr = slides[idx].tr || { kind: 'fade', dur: 0.6 };
    const tt = Number(params.get('tr')) * tr.dur;
    trans = { from: idx - 1, fromLt: slides[idx - 1].dur, t: tt, tr, dir: 1 };
    lt = tt;
  }

  function go(j, byAuto) {
    if (j < 0 || j >= N || j === idx) return;
    const dir = j > idx ? 1 : -1;
    const tr = dir > 0 ? slides[j].tr || { kind: 'fade', dur: 0.6 } : { kind: 'push', dur: 0.7 };
    trans = { from: idx, fromLt: lt, t: 0, tr, dir };
    idx = j;
    lt = 0;
    if (!byAuto) auto = false;
    if (FILM.audio) FILM.audio.onSlide(j, tr);
  }
  FILM.go = go;

  window.addEventListener('keydown', (ev) => {
    const k = ev.key;
    if (k === 'ArrowRight' || k === 'PageDown') go(idx + 1, false);
    else if (k === 'ArrowLeft' || k === 'PageUp') go(idx - 1, false);
    else if (k === ' ') paused = !paused;
    else if (k === 'Enter') { auto = true; paused = false; }
    else if (k === 'Home') { go(0, false); auto = true; }
    else if (k === 'End') go(N - 1, false);
    else if (k === 'f' || k === 'F' || k === 'а' || k === 'А') {
      if (!document.fullscreenElement) document.documentElement.requestFullscreen().catch(() => {});
      else document.exitFullscreen();
    } else if (k === 'm' || k === 'M' || k === 'ь' || k === 'Ь') {
      if (FILM.audio) FILM.audio.toggle();
    } else return;
    ev.preventDefault();
  });
  canvas.addEventListener('click', () => go(idx + 1, false));

  // ---------------------------------------------------------------------------
  // Цикл
  // ---------------------------------------------------------------------------

  let last = performance.now();
  let slowFrames = 0;
  let adaptUntil = 8;
  function frame(now) {
    let dt = (now - last) / 1000;
    last = now;
    if (dt > 0.1) dt = 0.1;
    if (!paused) {
      clock += dt;
      lt += dt;
      if (trans) trans.t += dt;
    }
    if (auto && !paused && !trans && lt >= slides[idx].dur && idx < N - 1) go(idx + 1, true);
    const t0 = performance.now();
    if (trans && trans.t < trans.tr.dur) {
      const p = clamp01(trans.t / trans.tr.dur);
      drawSlide(ctxA, trans.from, trans.fromLt + trans.t);
      drawSlide(ctxB, idx, lt);
      composite(trans.tr, layerA, layerB, p, trans.dir, slides[trans.from].mode);
    } else {
      trans = null;
      drawSlide(ctx, idx, lt);
    }
    hud(slides[idx].mode);
    // если кадр не укладывается в 1/40 с, понижаем разрешение (не ниже 60 процентов)
    if (clock < adaptUntil && !paused) {
      const cost = performance.now() - t0;
      slowFrames = cost > 25 ? slowFrames + 1 : Math.max(0, slowFrames - 1);
      if (slowFrames > 30 && quality > 0.6) {
        quality = Math.max(0.6, quality - 0.15);
        slowFrames = 0;
        adaptUntil = clock + 6;
        resize();
      }
    }
    requestAnimationFrame(frame);
  }
  // Отладка: прогон всего показа кадр за кадром с переходами, как в автопоказе.
  // Возвращает разницу соседних кадров (0..255) по уменьшенной копии: пики = скачки и мерцание.
  FILM.scan = (fps = 30, from = 0, to = N) => {
    const small = FILM.makeCanvas(160, 90);
    const sg = small.getContext('2d', { willReadFrequently: true });
    let prev = null, prev2 = null;
    const out = [];
    let clk = 0;
    for (let i = from; i < to; i++) {
      const s = slides[i];
      for (let k = 0; k * (1 / fps) < s.dur - 1e-6; k++) {
        const lt2 = k / fps;
        clock = clk;
        const tr = s.tr || { kind: 'fade', dur: 0.6 };
        if (i > from && lt2 < tr.dur) {
          drawSlide(ctxA, i - 1, slides[i - 1].dur + lt2);
          drawSlide(ctxB, i, lt2);
          composite(tr, layerA, layerB, clamp01(lt2 / tr.dur), 1, slides[i - 1].mode);
        } else drawSlide(ctx, i, lt2);
        sg.drawImage(canvas, 0, 0, 160, 90);
        const d = sg.getImageData(0, 0, 160, 90).data;
        const g = new Uint8Array(160 * 90);
        for (let p = 0; p < g.length; p++) g[p] = (d[p * 4] * 3 + d[p * 4 + 1] * 5 + d[p * 4 + 2] * 2) / 10;
        let diff = 0, flick = 0;
        if (prev) {
          for (let p = 0; p < g.length; p++) diff += Math.abs(g[p] - prev[p]);
          diff /= g.length;
        }
        if (prev2) {
          // мерцание: кадр вернулся к позапрошлому, а соседний от обоих отличается
          for (let p = 0; p < g.length; p++) flick += Math.max(0, Math.min(Math.abs(g[p] - prev[p]), Math.abs(prev[p] - prev2[p])) - Math.abs(g[p] - prev2[p]));
          flick /= g.length;
        }
        out.push([i, s.id, +lt2.toFixed(3), +diff.toFixed(2), +flick.toFixed(2)]);
        prev2 = prev;
        prev = g;
        clk += 1 / fps;
      }
    }
    return out;
  };

  // Отладка: один кадр слайда i на локальном времени lt при общем времени clk, как PNG
  FILM.shot = (i, lt2, clk) => {
    clock = clk;
    const tr = slides[i].tr || { kind: 'fade', dur: 0.6 };
    if (i > 0 && lt2 < tr.dur) {
      drawSlide(ctxA, i - 1, slides[i - 1].dur + lt2);
      drawSlide(ctxB, i, lt2);
      composite(tr, layerA, layerB, clamp01(lt2 / tr.dur), 1, slides[i - 1].mode);
    } else drawSlide(ctx, i, lt2);
    return canvas.toDataURL('image/png');
  };

  // Прогрев: бумага, синька и растровые слои каждого слайда строятся до показа,
  // иначе первый кадр нового листа стоит до 100 мс и рвёт переход.
  function loading(k) {
    resetCtx(ctx, true);
    ctx.fillStyle = P.paper;
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    base(ctx);
    lib.ticks(ctx, W / 2 - 300, H / 2 + 30, { length: 600, n: N * 3, len: 8, major: 3, majorLen: 18, color: P.ink, alpha: 0.5, width: 1.5, p: k / (N * 3) });
    lib.text(ctx, 'green', W / 2, H / 2, { size: 64, weight: 200, color: P.ink, align: 'center', tracking: 4 });
  }
  const warm = [];
  // три кадра на слайд: середина, поздняя часть и финал, каждый на своём варианте «кипения»
  for (let i = 0; i < N; i++) for (let v = 0; v < 4; v++) warm.push([i, v % 3, [0.18, 0.35, 0.7, 1.05][v] * slides[i].dur]);
  let wk = 0;
  function warmStep() {
    const t0 = performance.now();
    while (wk < warm.length && performance.now() - t0 < 40) {
      const [i, v, wt] = warm[wk++];
      const saved = clock;
      clock = v / 12 + 0.001;
      drawSlide(ctxA, i, wt);
      drawSlide(ctxB, i, wt);
      clock = saved;
    }
    if (wk < warm.length) {
      loading(wk);
      setTimeout(warmStep, 0);
    } else {
      requestAnimationFrame((now) => {
        last = now;
        frame(now);
      });
    }
  }
  loading(0);
  setTimeout(warmStep, 0);
})();
