/*
 * runtime.js : плеер презентации поверх FILM.lib (движок procedural-film, MIT).
 *
 * Слайд = { id, mode: 'paper' | 'blue', dur, tr: { kind, dur, x, y }, draw(ctx, t, info) }.
 * Сцена рисует кадр только из t (локальное время слайда) и не хранит состояние между кадрами.
 * После dur сцена получает t > dur и держит финальную позу; фоновое движение продолжается.
 *
 * Рисуем на частоте экрана (requestAnimationFrame): камера, переходы и проявления идут плавно,
 * линии «кипят» на 12 кадрах в секунду, как в рисованной анимации.
 */
(function () {
  'use strict';

  const FILM = (window.FILM = window.FILM || {});
  FILM.W = 1920;
  FILM.H = 1080;
  FILM.S = 1;
  FILM.frameT = 0;
  FILM.TIMELINE = { shots: new Array(40) };
  FILM.makeCanvas = (w, h) => {
    const c = document.createElement('canvas');
    c.width = w;
    c.height = h;
    return c;
  };
  FILM.SLIDES = [];
  FILM.slide = (def) => {
    FILM.SLIDES.push(def);
    return def;
  };
})();
