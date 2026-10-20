/* Знаки шаблона на холсте и загрузка файла знаков: данные - маленький искусственный файл, а не
 * настоящий templateSigns.json, чтобы по вызовам было видно каждый путь знака. */

import { beforeEach, describe, expect, it, vi } from 'vitest';

import { fakeContext, installCanvas, type InstalledCanvas, RecordingPath2D } from '../test/canvas';
import type { SignInk } from './signs';
import {
  loadTemplateSigns,
  onTemplateSigns,
  paintSign,
  setTemplateSignFile,
  signSprite,
  type TemplateSign,
  type TemplateSignFile,
  templateSignFile,
  templateSignOf,
  templateSignsVersion,
} from './templateSigns';

const LINDEN: TemplateSign = {
  name: 'Липа',
  section: 'tree',
  position: '12',
  blocks: ['ЛИПА'],
  tone: ['#00aa00', 1],
  aspect: 1,
  paths: [
    ['f', '#00aa00', 0.5, 0.25, 'M0 0L1 0L1 1Z'],
    ['s', 'ink', 1, 0.25, 'M0 0L0 1'],
  ],
};

const FILE: TemplateSignFile = {
  source: 'Шаблоны значков.dwg',
  converter: 'ODA',
  command: 'uv run tools/extract_template_signs.py',
  generated: '2026-10-01',
  hash: 'abc',
  empty_rows: [],
  signs: [LINDEN],
};

const LIGHT: SignInk = {
  ink: '#141414',
  paper: '#ffffff',
  crown: '',
  coniferCrown: '',
  coniferRing: '',
  halo: '',
};
const DARK: SignInk = { ...LIGHT, ink: '#ecebe6', paper: '#16191d' };

let canvas: InstalledCanvas;

beforeEach(() => {
  canvas = installCanvas();
});

describe('знак шаблона на холсте', () => {
  it('заливка по чётно-нечётному правилу с непрозрачностью пути, штрих чернилами в пикселях', () => {
    const fake = fakeContext();
    fake.ctx.globalAlpha = 0.8;
    paintSign(fake.ctx, LINDEN, 10, LIGHT);
    expect(fake.named('scale')[0]?.args).toEqual([10, 10]);
    const [fill] = fake.named('fill');
    expect(fill?.args[1]).toBe('evenodd');
    expect(fill?.state).toMatchObject({ fillStyle: '#00aa00', globalAlpha: 0.4 });
    const path = fill?.args[0];
    expect(path).toBeInstanceOf(RecordingPath2D);
    expect((path as RecordingPath2D).ops).toEqual([{ name: 'svg', args: ['M0 0L1 0L1 1Z'] }]);
    const [stroke] = fake.named('stroke');
    // Вес 0,25 мм: 0,6 px, на знаке радиусом 10 тоньше, но не тоньше 0,45 px.
    expect(stroke?.state).toMatchObject({ strokeStyle: '#141414', globalAlpha: 0.8 });
    expect(stroke?.state.lineWidth).toBeCloseTo(0.045);
    // Кисть возвращается к прежней непрозрачности.
    expect(fake.ctx.globalAlpha).toBe(0.8);
  });

  it('пути знака собираются один раз', () => {
    const first = fakeContext();
    const second = fakeContext();
    paintSign(first.ctx, LINDEN, 10, LIGHT);
    paintSign(second.ctx, LINDEN, 30, DARK);
    expect(second.named('fill')[0]?.args[0]).toBe(first.named('fill')[0]?.args[0]);
    // На крупном знаке штрих толще: 0,6 px целиком.
    expect(second.named('stroke')[0]?.state.lineWidth).toBeCloseTo(0.6 / 30);
    expect(second.named('stroke')[0]?.state.strokeStyle).toBe('#ecebe6');
  });
});

describe('спрайт знака', () => {
  it('сторона - знак с запасом в пикселях устройства, знак в центре', () => {
    const s = signSprite(LINDEN, 16, LIGHT, 2);
    expect(s.radius).toBe(16);
    expect(s.half).toBe(18);
    expect(s.canvas.width).toBe(72);
    const fake = canvas.of(s.canvas);
    expect(fake?.named('scale').map((c) => c.args)).toEqual([
      [2, 2],
      [16, 16],
    ]);
    expect(fake?.named('translate')[0]?.args).toEqual([18, 18]);
  });

  it('тот же знак, ступень, плотность и тема - тот же спрайт; другая тема - новый', () => {
    const a = signSprite(LINDEN, 12, LIGHT, 1);
    expect(signSprite(LINDEN, 12, LIGHT, 1)).toBe(a);
    expect(signSprite(LINDEN, 12, DARK, 1)).not.toBe(a);
    expect(signSprite(LINDEN, 12, LIGHT, 2)).not.toBe(a);
  });

  it('переполненный кэш начинается заново', () => {
    const first = signSprite(LINDEN, 1, LIGHT, 1);
    for (let i = 2; i < 700; i++) signSprite(LINDEN, 1, LIGHT, i);
    expect(signSprite(LINDEN, 1, LIGHT, 1)).not.toBe(first);
  });

  it('без контекста холста спрайт пустой, но с размером', () => {
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null);
    const s = signSprite(LINDEN, 40, DARK, 3);
    expect(s.half).toBe(Math.ceil(s.radius * 1.05 + 1));
    expect(canvas.of(s.canvas)).toBeUndefined();
  });
});

describe('загрузка файла знаков', () => {
  it('один запрос на страницу; пришёл файл - подписчики перерисовываются, версия растёт', async () => {
    const fetch = vi.fn(() => Promise.resolve(new Response(JSON.stringify(FILE), { status: 200 })));
    vi.stubGlobal('fetch', fetch);
    const listener = vi.fn();
    const off = onTemplateSigns(listener);
    const version = templateSignsVersion();
    await Promise.all([loadTemplateSigns(), loadTemplateSigns()]);
    expect(fetch).toHaveBeenCalledOnce();
    expect(listener).toHaveBeenCalledOnce();
    expect(templateSignsVersion()).toBe(version + 1);
    expect(templateSignFile()?.source).toBe('Шаблоны значков.dwg');
    expect(templateSignOf('Липа')?.position).toBe('12');
    off();
    setTemplateSignFile(FILE);
    expect(listener).toHaveBeenCalledOnce();
  });

  it('ответ с ошибкой не ломает карту: знаков нет, исключения нет', async () => {
    vi.resetModules();
    const fresh = await import('./templateSigns');
    vi.stubGlobal(
      'fetch',
      vi.fn(() => Promise.resolve(new Response('нет', { status: 503 }))),
    );
    await expect(fresh.loadTemplateSigns()).resolves.toBeUndefined();
    expect(fresh.templateSignFile()).toBeNull();
    expect(fresh.templateSignsVersion()).toBe(0);
  });
});
