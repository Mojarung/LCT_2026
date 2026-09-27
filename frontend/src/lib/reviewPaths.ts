/* Геометрия проверки -> путь холста в координатах чертежа. Перенос pathOf из review.js. */

import type { Geometry, Position } from '../api/artifacts';

/** Точка рисуется кружком радиусом 0,2 м: на общем виде её видно, на крупном она не
 *  закрывает соседей. */
const POINT_RADIUS_M = 0.2;

export function geometryPath(geometry: Geometry, path: Path2D = new Path2D()): Path2D {
  const line = (coordinates: readonly Position[], closed: boolean) => {
    coordinates.forEach(([x, y], index) => {
      if (index) path.lineTo(x, y);
      else path.moveTo(x, y);
    });
    if (closed) path.closePath();
  };
  switch (geometry.type) {
    case 'Point': {
      const [x, y] = geometry.coordinates;
      path.moveTo(x + POINT_RADIUS_M, y);
      path.arc(x, y, POINT_RADIUS_M, 0, Math.PI * 2);
      break;
    }
    case 'MultiPoint':
      for (const coordinates of geometry.coordinates) {
        geometryPath({ type: 'Point', coordinates }, path);
      }
      break;
    case 'LineString':
      line(geometry.coordinates, false);
      break;
    case 'MultiLineString':
      for (const coordinates of geometry.coordinates) line(coordinates, false);
      break;
    case 'Polygon':
      for (const ring of geometry.coordinates) line(ring, true);
      break;
    case 'MultiPolygon':
      for (const polygon of geometry.coordinates) for (const ring of polygon) line(ring, true);
      break;
    case 'GeometryCollection':
      for (const part of geometry.geometries) geometryPath(part, path);
      break;
  }
  return path;
}

/** Один путь на группу: карта обводит группу одним вызовом, а не объектом за объектом. */
export function joinPaths(paths: readonly Path2D[], indices: readonly number[]): Path2D {
  const path = new Path2D();
  for (const index of indices) {
    const own = paths[index];
    if (own) path.addPath(own);
  }
  return path;
}
