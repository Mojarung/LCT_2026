/* Геометрия проверки и отчёт классификации для тестов страницы уточнения объектов. */

import type { ClassificationJson, ReviewGeometry } from '../review';

/** Чертёж на три группы: неизвестная линия, уточнённый ранее слой и газон по правилу имени. */
export const REVIEW: ReviewGeometry = {
  source_sha256: 'abc123',
  features: [
    {
      id: 'f:1',
      geometry: {
        type: 'LineString',
        coordinates: [
          [0, 0],
          [10, 0],
        ],
      },
      properties: {
        group: 0,
        class: 'unknown',
        error_m: 0,
        source_entity_type: 'LINE',
        bounds: [0, 0, 10, 0],
      },
    },
    {
      id: 'f:2',
      geometry: { type: 'Point', coordinates: [5, 5] },
      properties: { group: 1, class: 'pole', error_m: 0, bounds: [5, 5, 5, 5] },
    },
    {
      id: 'f:3',
      geometry: {
        type: 'LineString',
        coordinates: [
          [0, 10],
          [20, 10],
        ],
      },
      properties: { group: 0, class: 'unknown', error_m: 0.01, bounds: [0, 10, 20, 12] },
    },
    {
      id: 'f:4',
      geometry: {
        type: 'Polygon',
        coordinates: [
          [
            [0, 0],
            [1, 0],
            [1, 1],
            [0, 0],
          ],
        ],
      },
      properties: { group: 2, class: 'lawn', error_m: 0, bounds: [-5, -2, 1, 1] },
    },
  ],
  labels: [
    { id: 'l:1', layer: 'Подписи', x: 1, y: 1, text: 'ГАЗОН', surface_role: 'soil' },
    {
      id: 'l:2',
      layer: 'Подписи',
      x: 2,
      y: 2,
      text: 'А',
      surface_role: 'paved',
      evidence: { method: 'explicit_label' },
    },
  ],
};

export const REPORT: ClassificationJson = {
  source_sha256: 'abc123',
  ready: false,
  groups: [
    {
      layer: '0',
      block: null,
      geometry: 'LineString',
      object_class: 'unknown',
      evidence: { method: 'unmatched' },
      features: 2,
    },
    {
      layer: 'Опоры',
      block: null,
      geometry: 'Point',
      object_class: 'pole',
      evidence: { method: 'explicit_layer' },
      features: 1,
    },
    {
      layer: 'Газон',
      block: null,
      geometry: 'Polygon',
      object_class: 'lawn',
      evidence: { method: 'name_rule' },
      features: 1,
    },
  ],
};
