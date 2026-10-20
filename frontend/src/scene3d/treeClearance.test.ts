import * as THREE from 'three';
import { describe, expect, it, vi } from 'vitest';
import type { Rule, RulesJson } from '../api/artifacts';
import type { Building, Plant, Ring } from './types';
import { buildWorld, speciesFallback } from './world';
import { pickTreeWarning, treeClearanceConflicts, TREE_WARNING_Y } from './treeClearance';
import { treeWarningOverlay } from './treeWarningOverlay';

const ring = (x: number, z: number, size: number): Ring => [
  { x, z },
  { x: x + size, z },
  { x: x + size, z: z + size },
  { x, z: z + size },
];
const building = (rings: Ring[]): Building => ({
  rings,
  kind: 'building',
  height: 16,
  floors: 5,
  source: 'label',
  wall: null,
  use: null,
  seed: 1,
});
const plant = (id: string, x: number, z: number, extra: Partial<Plant> = {}): Plant => ({
  id,
  x,
  z,
  type: 'existing_tree',
  existing: true,
  code: 'existing_tree',
  name: 'Существующее дерево',
  species: speciesFallback('', 'tree_large', ''),
  seed: 1,
  ...extra,
});
const rule: Rule = {
  rule_id: 'R-BLD-TREE-001',
  object_class: 'building',
  min_distance_m: 5,
  measure_to: 'edge',
  status: 'verified',
  severity: 'forbid',
  act_id: 'SP42',
  act_title: 'СП 42',
  act_short: 'СП 42',
  act_edition: '',
  url: '',
  clause: 'табл. 9.1',
  quote: '',
  related: [],
};
const rules: RulesJson = { fingerprint: 'test', total: 1, rules: { [rule.rule_id]: rule } };
function world() {
  const w = buildWorld({ scene: null, plan: null, basemap: null });
  w.buildings = [building([ring(0, 0, 10)])];
  return w;
}

describe('отступ существующих деревьев до здания', () => {
  it('отмечает стволы ближе нормы, включая точку внутри здания, но не граничный отступ', () => {
    const w = world();
    w.plants = [
      plant('near', -1.31, 5),
      plant('inside', 5, 5),
      plant('limit', -5, 5),
      plant('far', -6, 5),
      plant('corner', -3, -4),
    ];
    const result = treeClearanceConflicts(w, rules);
    expect(result.map((c) => c.plant.id)).toEqual(['near', 'inside']);
    expect(result[0]?.distance).toBeCloseTo(1.31);
    expect(result[0]?.required).toBe(5);
    expect(result[1]?.distance).toBe(0);
  });

  it('не выдаёт новые посадки, кусты, полосы и крыльцо за существующее дерево у стены дома', () => {
    const w = world();
    w.buildings = [{ ...building([ring(0, 0, 10)]), kind: 'porch' }];
    w.plants = [plant('tree', -1, 5)];
    expect(treeClearanceConflicts(w, rules)).toEqual([]);
    w.buildings = [building([ring(0, 0, 10)])];
    w.plants = [
      plant('new', -1, 5, { existing: false, type: 'tree' }),
      plant('strip', -1, 5, { strip: true }),
      plant('shrub', -1, 5, { type: 'existing_shrub' }),
    ];
    expect(treeClearanceConflicts(w, rules)).toEqual([]);
  });

  it('учитывает внутренний двор и расстояние до ближайшей из его стен', () => {
    const w = world();
    w.buildings = [building([ring(0, 0, 30), ring(5, 5, 20)])];
    w.plants = [plant('courtyard-near', 6.98, 15), plant('courtyard-center', 15, 15)];
    const conflicts = treeClearanceConflicts(w, rules);
    expect(conflicts).toHaveLength(1);
    expect(conflicts[0]?.distance).toBeCloseTo(1.98);
  });

  it('использует порог из правил прогона и не подставляет норму при отсутствии проверенного правила', () => {
    const w = world();
    w.plants = [plant('tree', -3, 5)];
    expect(treeClearanceConflicts(w, null)).toEqual([]);
    for (const change of [
      { status: 'unverified' },
      { min_distance_m: null },
      { min_distance_m: NaN },
      { measure_to: 'center' },
    ]) {
      expect(
        treeClearanceConflicts(w, { ...rules, rules: { [rule.rule_id]: { ...rule, ...change } } }),
      ).toEqual([]);
    }
    expect(
      treeClearanceConflicts(w, {
        ...rules,
        rules: { [rule.rule_id]: { ...rule, min_distance_m: 2 } },
      }),
    ).toEqual([]);
  });

  it('открывает пояснение при наведении на красную область на земле', () => {
    const w = world();
    w.plants = [plant('tree', -1.31, 5)];
    const conflicts = treeClearanceConflicts(w, rules);
    const ray = { ox: -1.31, oy: 5, oz: 5, dx: 0, dy: -1, dz: 0 };
    expect(pickTreeWarning(ray, conflicts)).toBe('tree');
    expect(pickTreeWarning({ ...ray, ox: -10 }, conflicts)).toBeNull();
    expect(pickTreeWarning({ ...ray, dy: 1 }, conflicts)).toBeNull();
  });

  it('рисует две группы инстансов поверх земли и освобождает их GPU-ресурсы', () => {
    const w = world();
    w.plants = [plant('tree', -1.31, 5)];
    const overlay = treeWarningOverlay(treeClearanceConflicts(w, rules));
    const meshes = overlay.group.children as THREE.InstancedMesh[];
    expect(meshes).toHaveLength(2);
    for (const mesh of meshes) {
      expect(mesh.count).toBe(1);
      const matrix = new THREE.Matrix4();
      mesh.getMatrixAt(0, matrix);
      const at = new THREE.Vector3().setFromMatrixPosition(matrix);
      expect(at.x).toBeCloseTo(-1.31);
      expect(at.y).toBeGreaterThanOrEqual(TREE_WARNING_Y);
      expect(at.z).toBe(5);
    }
    const resources = meshes.flatMap((mesh) => [
      mesh,
      mesh.geometry,
      ...(Array.isArray(mesh.material) ? mesh.material : [mesh.material]),
    ]);
    const disposed = resources.map((r) => vi.spyOn(r, 'dispose'));
    overlay.dispose();
    for (const spy of disposed) expect(spy).toHaveBeenCalledOnce();
  });
});
