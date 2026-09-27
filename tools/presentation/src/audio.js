/*
 * audio.js : звук синтезируется в Web Audio, файлов нет. Выключен, пока не нажата M.
 * Пэд держит аккорд слайда, на смене слайда глухой удар и колокольчик, на каждой доле тихий щелчок.
 */
(function () {
  'use strict';

  const FILM = window.FILM;
  let ac = null;
  let master = null;
  let on = false;
  let pad = [];
  let tickTimer = null;

  // аккорды по кругу: ля минор, фа, до, соль, ре минор (частоты в герцах)
  const CHORDS = [
    [220.0, 261.63, 329.63, 392.0],
    [174.61, 220.0, 261.63, 329.63],
    [196.0, 261.63, 329.63, 392.0],
    [196.0, 246.94, 293.66, 392.0],
    [146.83, 220.0, 293.66, 349.23],
  ];

  function ensure() {
    if (ac) return;
    ac = new (window.AudioContext || window.webkitAudioContext)();
    master = ac.createGain();
    master.gain.value = 0;
    const comp = ac.createDynamicsCompressor();
    comp.threshold.value = -18;
    master.connect(comp);
    comp.connect(ac.destination);
  }

  function setPad(i) {
    const now = ac.currentTime;
    for (const v of pad) {
      v.g.gain.cancelScheduledValues(now);
      v.g.gain.setTargetAtTime(0, now, 0.6);
      v.o.stop(now + 4);
    }
    pad = [];
    const chord = CHORDS[i % CHORDS.length];
    chord.forEach((f, k) => {
      for (const det of [-4, 5]) {
        const o = ac.createOscillator();
        o.type = k === 0 ? 'triangle' : 'sawtooth';
        o.frequency.value = f / (k === 0 ? 2 : 1);
        o.detune.value = det;
        const flt = ac.createBiquadFilter();
        flt.type = 'lowpass';
        flt.frequency.value = 900;
        flt.Q.value = 0.4;
        const g = ac.createGain();
        g.gain.value = 0;
        g.gain.setTargetAtTime(k === 0 ? 0.05 : 0.016, now, 1.2);
        o.connect(flt);
        flt.connect(g);
        g.connect(master);
        o.start(now);
        pad.push({ o, g });
      }
    });
  }

  function hit(freq, dur, vol, type) {
    const now = ac.currentTime;
    const o = ac.createOscillator();
    o.type = type || 'sine';
    o.frequency.setValueAtTime(freq, now);
    if (!type) o.frequency.exponentialRampToValueAtTime(freq * 0.5, now + dur);
    const g = ac.createGain();
    g.gain.setValueAtTime(vol, now);
    g.gain.exponentialRampToValueAtTime(0.0001, now + dur);
    o.connect(g);
    g.connect(master);
    o.start(now);
    o.stop(now + dur + 0.05);
  }

  function tick() {
    if (!on) return;
    const now = ac.currentTime;
    const len = Math.floor(ac.sampleRate * 0.02);
    const buf = ac.createBuffer(1, len, ac.sampleRate);
    const d = buf.getChannelData(0);
    for (let i = 0; i < len; i++) d[i] = (Math.random() * 2 - 1) * Math.pow(1 - i / len, 3);
    const src = ac.createBufferSource();
    src.buffer = buf;
    const flt = ac.createBiquadFilter();
    flt.type = 'highpass';
    flt.frequency.value = 3500;
    const g = ac.createGain();
    g.gain.value = 0.05;
    src.connect(flt);
    flt.connect(g);
    g.connect(master);
    src.start(now);
  }

  let current = 0;
  FILM.audio = {
    toggle() {
      ensure();
      on = !on;
      if (ac.state === 'suspended') ac.resume();
      master.gain.setTargetAtTime(on ? 0.9 : 0, ac.currentTime, 0.3);
      if (on) {
        setPad(current);
        tickTimer = setInterval(tick, 500);
      } else {
        clearInterval(tickTimer);
      }
    },
    onSlide(i) {
      current = i;
      if (!on) return;
      setPad(i);
      hit(110, 0.5, 0.35);
      hit(CHORDS[i % CHORDS.length][3] * 2, 1.2, 0.05, 'sine');
    },
  };
})();
