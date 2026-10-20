import * as THREE from 'three';
import { TREE_WARNING_RADIUS, TREE_WARNING_Y, type TreeClearanceConflict } from './treeClearance';

/** Два instanced-меша на весь участок: маркеры не добавляют по draw call на каждое дерево. */
export function treeWarningOverlay(conflicts: readonly TreeClearanceConflict[]) {
  const group = new THREE.Group();
  group.name = 'existing-tree-clearance';
  const fillGeometry = new THREE.CircleGeometry(TREE_WARNING_RADIUS, 48);
  const rimGeometry = new THREE.RingGeometry(
    TREE_WARNING_RADIUS - 0.06,
    TREE_WARNING_RADIUS + 0.06,
    48,
  );
  fillGeometry.rotateX(-Math.PI / 2);
  rimGeometry.rotateX(-Math.PI / 2);
  const fillMaterial = new THREE.MeshBasicMaterial({
    color: 0xd83e3e,
    transparent: true,
    opacity: 0.26,
    depthWrite: false,
    side: THREE.DoubleSide,
    toneMapped: false,
  });
  const rimMaterial = new THREE.MeshBasicMaterial({
    color: 0xe83232,
    transparent: true,
    opacity: 0.95,
    depthWrite: false,
    side: THREE.DoubleSide,
    toneMapped: false,
  });
  const fill = new THREE.InstancedMesh(fillGeometry, fillMaterial, conflicts.length);
  const rim = new THREE.InstancedMesh(rimGeometry, rimMaterial, conflicts.length);
  const transform = new THREE.Matrix4();
  conflicts.forEach(({ plant }, i) => {
    transform.makeTranslation(plant.x, TREE_WARNING_Y, plant.z);
    fill.setMatrixAt(i, transform);
    transform.makeTranslation(plant.x, TREE_WARNING_Y + 0.005, plant.z);
    rim.setMatrixAt(i, transform);
  });
  fill.instanceMatrix.needsUpdate = true;
  rim.instanceMatrix.needsUpdate = true;
  fill.renderOrder = 3;
  rim.renderOrder = 4;
  group.add(fill, rim);
  return {
    group,
    dispose() {
      fill.dispose();
      rim.dispose();
      fillGeometry.dispose();
      rimGeometry.dispose();
      fillMaterial.dispose();
      rimMaterial.dispose();
    },
  };
}
