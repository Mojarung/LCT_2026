/* Типы артефактов прогона, которые читает браузер. Источник формы - сериализаторы в
 * src/green/infrastructure/reports/artifacts.py (_plan, _rules, _quality, _basemap, _surface):
 * при правке там правится и здесь. */

export interface RuleCheck {
  rule_id: string;
  outcome: string; // pass | fail | no_data | barrier | species
  measured_m: number | null;
  threshold_m: number | null;
  object_class: string | null;
  nearest_ref?: string | null;
}

export interface Rule {
  rule_id: string;
  object_class: string;
  min_distance_m: number | null;
  measure_to: string;
  severity: string;
  act_id: string;
  act_title: string;
  act_short: string;
  act_edition: string;
  url: string;
  clause: string;
  quote: string;
  status: string;
  related: string[];
}

export interface RulesJson {
  fingerprint: string;
  total: number;
  rules: Record<string, Rule>;
}

export interface SpeciesBrief {
  code: string;
  name_ru: string;
  name_lat: string;
  crown_diameter_m: number;
  life_form: string;
}

export interface AssortmentReason {
  kind: string;
  text: string;
  rule_id: string | null;
  source: string | null;
  condition: string | null;
}

export interface Assortment {
  status: string;
  percent: number;
  factors: Record<string, number>;
  structure: { id: string | null; kind: string | null };
  reasons: AssortmentReason[];
  alternatives: { code: string; name_ru: string; percent: number; why_not: string }[];
}

export interface PlantingValue {
  delta: number;
  percentile: number | null;
  by_term: Record<string, number>;
  reasons: string[];
  weak: string[];
  flagged?: boolean;
}

export interface PlacementJson {
  id: string;
  number: number;
  planting_type: string;
  species: SpeciesBrief | null;
  x: number;
  y: number;
  verdict: string;
  notes: string[];
  explanation: string;
  assortment: Assortment | null;
  value: PlantingValue | null;
  checks: RuleCheck[];
}

export interface RejectionJson {
  id: string;
  number: number;
  planting_type: string;
  x: number;
  y: number;
  verdict: string;
  note: string;
  barrier_m: number | null;
  explanation: string;
  blocking: RuleCheck[];
}

export interface PlanJson {
  run_id: string;
  source: { name: string; sha256: string; dxf_version: string };
  summary: Record<string, unknown>;
  placements: PlacementJson[];
  rejections: RejectionJson[];
  warnings: string[];
}

export interface QualityTerm {
  key: string;
  title: string;
  weight: number;
  score: number | null;
  basis: string;
  note: string;
  measure: Record<string, unknown>;
}

export interface QualityJson {
  index: number | null;
  gate: string;
  summary?: string[];
  terms?: QualityTerm[];
  penalty?: number;
  penalties?: Record<string, number>;
  top?: { id: string; delta: number; reasons: string[] }[];
  negative?: { id: string; delta: number; weak: string[] }[];
}

export type Position = [number, number];

export type Geometry =
  | { type: 'Point'; coordinates: Position }
  | { type: 'MultiPoint'; coordinates: Position[] }
  | { type: 'LineString'; coordinates: Position[] }
  | { type: 'MultiLineString'; coordinates: Position[][] }
  | { type: 'Polygon'; coordinates: Position[][] }
  | { type: 'MultiPolygon'; coordinates: Position[][][] }
  | { type: 'GeometryCollection'; geometries: Geometry[] };

export interface BasemapFeature {
  type: 'Feature';
  properties: { class: string };
  geometry: Geometry;
}

/** Подпись материала с чертежа: x, y, текст, paved | soil. */
export type MaterialLabel = [number, number, string, string];

export interface BasemapJson {
  type: 'FeatureCollection';
  bbox: [number, number, number, number];
  labels?: MaterialLabel[];
  features: BasemapFeature[];
  counts?: Record<string, unknown>;
}

export interface SurfaceMeta {
  origin: [number, number];
  cell_m: number;
  width: number;
  height: number;
}
