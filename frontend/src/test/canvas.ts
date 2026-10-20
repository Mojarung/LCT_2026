/* Записывающий холст для тестов карты: jsdom не рисует canvas, поэтому контекст 2D и Path2D
 * подменяются объектами, которые запоминают каждый вызов вместе с состоянием кисти. Тест
 * проверяет, что нарисовано, где и каким цветом, а не пиксели. */

import { vi } from 'vitest';

/** Состояние кисти в момент вызова: по нему видно, каким цветом и толщиной шла линия. */
export interface BrushState {
  fillStyle: unknown;
  strokeStyle: unknown;
  lineWidth: number;
  globalAlpha: number;
  font: string;
  textAlign: string;
  textBaseline: string;
  globalCompositeOperation: string;
  lineDash: number[];
}

export interface CanvasCall {
  name: string;
  args: unknown[];
  state: BrushState;
}

/** Path2D, который запоминает свои команды. */
export class RecordingPath2D {
  readonly ops: { name: string; args: unknown[] }[] = [];
  constructor(source?: RecordingPath2D | string) {
    if (source instanceof RecordingPath2D) this.ops.push(...source.ops);
    else if (typeof source === 'string') this.ops.push({ name: 'svg', args: [source] });
  }
}
const PATH_METHODS = [
  'moveTo',
  'lineTo',
  'arc',
  'arcTo',
  'rect',
  'roundRect',
  'ellipse',
  'closePath',
  'bezierCurveTo',
  'quadraticCurveTo',
  'addPath',
] as const;
for (const name of PATH_METHODS) {
  (RecordingPath2D.prototype as unknown as Record<string, unknown>)[name] = function (
    this: RecordingPath2D,
    ...args: unknown[]
  ) {
    this.ops.push({ name, args });
  };
}

export interface FakeContext {
  ctx: CanvasRenderingContext2D;
  calls: CanvasCall[];
  /** Вызовы одного метода. */
  named(name: string): CanvasCall[];
  /** Тексты всех fillText по порядку. */
  texts(): string[];
  reset(): void;
}

const DEFAULTS = {
  fillStyle: '#000000',
  strokeStyle: '#000000',
  lineWidth: 1,
  globalAlpha: 1,
  font: '10px sans-serif',
  textAlign: 'start',
  textBaseline: 'alphabetic',
  globalCompositeOperation: 'source-over',
  lineCap: 'butt',
  lineJoin: 'miter',
  miterLimit: 10,
  lineDashOffset: 0,
  shadowColor: 'rgba(0, 0, 0, 0)',
  shadowBlur: 0,
  shadowOffsetX: 0,
  shadowOffsetY: 0,
  imageSmoothingEnabled: true,
  imageSmoothingQuality: 'low',
  filter: 'none',
  direction: 'inherit',
  letterSpacing: '0px',
};

/** Ширина текста по числу знаков: этого хватает, чтобы подписи раскладывались детерминированно. */
export const CHAR_PX = 6;

/** Чем отвечает getImageData: по умолчанию прозрачные нули, тест может подложить свой растр. */
export interface CanvasOptions {
  pixels?: (width: number, height: number) => Uint8ClampedArray;
}

export function fakeContext(
  canvas: { width: number; height: number } = { width: 800, height: 600 },
  options: CanvasOptions = {},
): FakeContext {
  const calls: CanvasCall[] = [];
  const props: Record<string, unknown> = { ...DEFAULTS, canvas };
  let dash: number[] = [];
  const stack: { props: Record<string, unknown>; dash: number[] }[] = [];
  const snapshot = (): BrushState => ({
    fillStyle: props.fillStyle,
    strokeStyle: props.strokeStyle,
    lineWidth: props.lineWidth as number,
    globalAlpha: props.globalAlpha as number,
    font: props.font as string,
    textAlign: props.textAlign as string,
    textBaseline: props.textBaseline as string,
    globalCompositeOperation: props.globalCompositeOperation as string,
    lineDash: [...dash],
  });
  const special: Record<string, (...args: unknown[]) => unknown> = {
    save: () => stack.push({ props: { ...props }, dash: [...dash] }),
    restore: () => {
      const top = stack.pop();
      if (!top) return;
      for (const key of Object.keys(props)) Reflect.deleteProperty(props, key);
      Object.assign(props, top.props);
      dash = top.dash;
    },
    setLineDash: (segments) => {
      dash = [...(segments as number[])];
    },
    getLineDash: () => [...dash],
    measureText: (text) => ({
      width: String(text).length * CHAR_PX,
      actualBoundingBoxAscent: 8,
      actualBoundingBoxDescent: 2,
      actualBoundingBoxLeft: 0,
      actualBoundingBoxRight: String(text).length * CHAR_PX,
      fontBoundingBoxAscent: 9,
      fontBoundingBoxDescent: 3,
    }),
    createPattern: (image, repetition) => ({ image, repetition, setTransform: vi.fn() }),
    createLinearGradient: (...args) => ({ kind: 'linear', args, addColorStop: vi.fn() }),
    createRadialGradient: (...args) => ({ kind: 'radial', args, addColorStop: vi.fn() }),
    getTransform: () => new DOMMatrixStub(),
    getImageData: (_x, _y, w, h) => ({
      width: w,
      height: h,
      data:
        options.pixels?.(w as number, h as number) ??
        new Uint8ClampedArray((w as number) * (h as number) * 4),
    }),
    createImageData: (w, h) => ({
      width: w,
      height: h,
      data: new Uint8ClampedArray((w as number) * (h as number) * 4),
    }),
    isPointInPath: () => false,
    isPointInStroke: () => false,
  };
  const fns = new Map<string, (...args: unknown[]) => unknown>();
  const ctx = new Proxy(
    {},
    {
      get(_target, key) {
        if (typeof key !== 'string') return undefined;
        if (key in props) return props[key];
        let fn = fns.get(key);
        if (!fn) {
          fn = (...args: unknown[]) => {
            calls.push({ name: key, args, state: snapshot() });
            return special[key]?.(...args);
          };
          fns.set(key, fn);
        }
        return fn;
      },
      set(_target, key, value) {
        if (typeof key === 'string') props[key] = value;
        return true;
      },
      has(_target, key) {
        return typeof key === 'string';
      },
    },
  ) as unknown as CanvasRenderingContext2D;
  return {
    ctx,
    calls,
    named: (name) => calls.filter((c) => c.name === name),
    texts: () => calls.filter((c) => c.name === 'fillText').map((c) => String(c.args[0])),
    reset: () => {
      calls.length = 0;
    },
  };
}

/** Единичная матрица: getTransform нужен коду, который переносит узор на экран. */
class DOMMatrixStub {
  a = 1;
  b = 0;
  c = 0;
  d = 1;
  e = 0;
  f = 0;
  inverse(): DOMMatrixStub {
    return new DOMMatrixStub();
  }
  multiply(): DOMMatrixStub {
    return new DOMMatrixStub();
  }
}

/** ImageData без canvas-пакета: в jsdom его нет. */
export class FakeImageData {
  readonly data: Uint8ClampedArray;
  constructor(
    public width: number,
    public height: number,
  ) {
    this.data = new Uint8ClampedArray(width * height * 4);
  }
}

/** Подменить ImageData и DOMMatrix, которых нет в jsdom (снимается vi.unstubAllGlobals). */
export function installImaging(): void {
  vi.stubGlobal('ImageData', FakeImageData);
  vi.stubGlobal('DOMMatrix', DOMMatrixStub);
}

/** Холст вне документа: размер и записывающий контекст. */
export class FakeOffscreenCanvas {
  readonly fake: FakeContext;
  constructor(
    public width: number,
    public height: number,
  ) {
    this.fake = fakeContext(this);
  }
  getContext(): CanvasRenderingContext2D {
    return this.fake.ctx;
  }
}

/** Все контексты, созданные через document.createElement('canvas') после installCanvas. */
export interface InstalledCanvas {
  contexts: FakeContext[];
  /** Записывающий контекст данного холста (если у него уже просили getContext). */
  of(canvas: HTMLCanvasElement): FakeContext | undefined;
}

/** Подменить Path2D, OffscreenCanvas и getContext у HTMLCanvasElement. Снимается само:
 *  setup.ts вызывает vi.unstubAllGlobals, а restoreMocks возвращает getContext. */
export function installCanvas(options: CanvasOptions = {}): InstalledCanvas {
  const contexts: FakeContext[] = [];
  vi.stubGlobal('Path2D', RecordingPath2D);
  vi.stubGlobal('OffscreenCanvas', FakeOffscreenCanvas);
  const own = new WeakMap<HTMLCanvasElement, FakeContext>();
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockImplementation(function (
    this: HTMLCanvasElement,
  ) {
    let fake = own.get(this);
    if (!fake) {
      fake = fakeContext(this, options);
      own.set(this, fake);
      contexts.push(fake);
    }
    return fake.ctx as unknown as RenderingContext;
  } as HTMLCanvasElement['getContext']);
  return { contexts, of: (canvas) => own.get(canvas) };
}
