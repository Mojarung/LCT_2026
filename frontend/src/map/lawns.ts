/* Газоны плана -> куски карты. Газон считает сервис (application/lawns.py): грунт, который
 * посадки оставили свободным, сохраняемый по чертежу или устраиваемый. На карте это тон и
 * контур поверх травы карты покрытий, своим слоем «lawns», который выключается в обозначениях.
 * Куски режутся той же нарезкой, что подоснова: отсечение по кадру и по размеру общее. */

import type { BasemapFeature, LawnJson } from '../api/artifacts';
import { buildChunks, type Chunk } from './chunks';
import { type Box, measure } from './geometry';

/** Класс куска по виду газона; стиль класса - в STYLES (palette.ts). */
export const LAWN_CLASSES: Readonly<Record<string, string>> = {
  kept: 'plan_lawn.kept',
  new: 'plan_lawn.new',
};

/** Газоны как объекты подосновы. Вид, которого карта не знает, не рисуется: цвет без
 *  обозначения в легенде ничего бы не сказал. */
export function lawnFeatures(lawns: readonly LawnJson[]): BasemapFeature[] {
  const features: BasemapFeature[] = [];
  for (const lawn of lawns) {
    const klass = LAWN_CLASSES[lawn.kind];
    if (klass)
      features.push({ type: 'Feature', properties: { class: klass }, geometry: lawn.geometry });
  }
  return features;
}

export function lawnChunks(lawns: readonly LawnJson[]): Chunk[] {
  const features = lawnFeatures(lawns);
  const box: Box = [Infinity, Infinity, -Infinity, -Infinity];
  for (const feature of features) measure(feature.geometry, box);
  return buildChunks(features, Number.isFinite(box[0]) ? box : null);
}

/** Куски подосновы и газонов в порядке отрисовки: газон ложится на заливки подосновы (траву
 *  карты покрытий и контуры газона чертежа), но под её линии - борта и сети видны поверх. */
export function withLawns(base: readonly Chunk[], lawns: readonly Chunk[]): Chunk[] {
  return [...base.filter((c) => c.fillVar), ...lawns, ...base.filter((c) => !c.fillVar)];
}
