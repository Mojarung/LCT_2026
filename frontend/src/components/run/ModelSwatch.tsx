import { useEffect, useRef, useSyncExternalStore } from 'react';

import type { Form, PlantModel } from '../../map/models';
import { Palette } from '../../map/palette';
import { drawSignSwatch, signInk, type SwatchSign } from '../../map/signs';
import { type Look, sprite, stamp } from '../../map/sprites';
import type { MapStyle } from '../../map/style';
import { useWorkspace } from '../../state/workspace';

/** Тема документа: знаки чертежа берут чернила из токенов, и в тёмной теме они светлые.
 *  Переключатель темы меняет атрибут напрямую, мимо хранилища, - поэтому подписка на него. */
function subscribeTheme(notify: () => void): () => void {
  const observer = new MutationObserver(notify);
  observer.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
  return () => {
    observer.disconnect();
  };
}

function useTheme(): string {
  return useSyncExternalStore(subscribeTheme, () => document.documentElement.dataset.theme ?? '');
}

const SHRUB_FORMS: ReadonlySet<Form> = new Set(['shrub', 'creeper']);
const CONIFER_FORMS: ReadonlySet<Form> = new Set(['conifer', 'dwarf_conifer']);

/** Знак чертежа для модели: тип посадки знает вызывающий, иначе он выводится из формы. */
function signOf(model: PlantModel, look: Look, shrub: boolean | undefined): SwatchSign {
  const isShrub = shrub ?? SHRUB_FORMS.has(model.form);
  if (look === 'existing') return isShrub ? 'existing-shrub' : 'existing-tree';
  if (isShrub) return 'shrub';
  return CONIFER_FORMS.has(model.form) ? 'conifer' : 'tree';
}

/** Образец знака чертежа: легенда инженерного стиля. */
export function SignSwatch({ sign, size = 26 }: { sign: SwatchSign; size?: number }) {
  const ref = useRef<HTMLCanvasElement>(null);
  const theme = useTheme();
  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = Math.round(size * dpr);
    canvas.height = Math.round(size * dpr);
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, size, size);
    drawSignSwatch(ctx, sign, size, signInk(new Palette()), dpr);
  }, [sign, size, theme]);
  return (
    <canvas
      ref={ref}
      className="model-swatch"
      style={{ width: `${String(size)}px`, height: `${String(size)}px` }}
      aria-hidden="true"
    />
  );
}

/** Образец модели растения тем же спрайтом или знаком, что на карте: обозначение в легенде и
 *  в составе плана не может разойтись с тем, что нарисовано на плане. Стиль - как у карты;
 *  база моделей передаёт style="illustrated": там смотрят сами модели. */
export function ModelSwatch({
  model,
  modelKey,
  look = 'plan',
  size = 26,
  shrub,
  style,
}: {
  model: PlantModel;
  modelKey: string;
  look?: Look;
  size?: number;
  /** Посадка - кустарник (по типу посадки); без него - по форме модели. */
  shrub?: boolean;
  style?: MapStyle;
}) {
  const current = useWorkspace((s) => s.mapStyle);
  const drawn = style ?? current;
  if (drawn === 'engineering') return <SignSwatch sign={signOf(model, look, shrub)} size={size} />;
  return <ModelSprite model={model} modelKey={modelKey} look={look} size={size} />;
}

function ModelSprite({
  model,
  modelKey,
  look,
  size,
}: {
  model: PlantModel;
  modelKey: string;
  look: Look;
  size: number;
}) {
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = Math.round(size * dpr);
    canvas.height = Math.round(size * dpr);
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, size, size);
    // Крона чуть левее и выше центра: тень уходит вниз-вправо и должна поместиться.
    const radius = size * 0.36;
    stamp(ctx, sprite(modelKey, model, radius, look, dpr), size / 2 - 1.5, size / 2 - 1.5, radius);
  }, [model, modelKey, look, size]);
  return (
    <canvas
      ref={ref}
      className="model-swatch"
      style={{ width: `${String(size)}px`, height: `${String(size)}px` }}
      aria-hidden="true"
    />
  );
}
