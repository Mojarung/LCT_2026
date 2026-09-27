/* Зоны допустимости -> куски карты. Зону считает сервис (application/zones.py): клетки по
 * метру, в любой точке которых дерево проходит все нормы, склеенные по вердикту; те же зоны
 * лежат в DXF на слоях GREEN_ZONE_*. На карте это тон и контур своим слоем «zones», по
 * умолчанию выключенным: зона отвечает на вопрос «где вообще можно сажать», а не входит в план. */

import type { BasemapFeature, ZonesJson } from '../api/artifacts';
import { buildChunks, type Chunk } from './chunks';
import { type Box, measure } from './geometry';

/** Класс куска по вердикту зоны; стиль класса - в STYLES (palette.ts). */
export const ZONE_CLASSES: Readonly<Record<string, string>> = {
  allowed: 'zone.allowed',
  needs_approval: 'zone.needs_approval',
};

/** Зоны как объекты подосновы. Вердикт, которого карта не знает, не рисуется: цвет без
 *  обозначения в легенде ничего бы не сказал. */
export function zoneFeatures(zones: ZonesJson | undefined): BasemapFeature[] {
  const features: BasemapFeature[] = [];
  for (const zone of zones?.features ?? []) {
    const klass = ZONE_CLASSES[zone.properties.verdict];
    if (klass)
      features.push({ type: 'Feature', properties: { class: klass }, geometry: zone.geometry });
  }
  return features;
}

export function zoneChunks(zones: ZonesJson | undefined): Chunk[] {
  const features = zoneFeatures(zones);
  const box: Box = [Infinity, Infinity, -Infinity, -Infinity];
  for (const feature of features) measure(feature.geometry, box);
  return buildChunks(features, Number.isFinite(box[0]) ? box : null);
}
