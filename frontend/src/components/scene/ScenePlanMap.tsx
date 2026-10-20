import { useEffect, useMemo, useRef, useState } from 'react';
import type { BasemapJson, PlanJson, SurfaceMeta } from '../../api/artifacts';
import { useArtifact } from '../../api/queries';
import { PlanEngine } from '../../map/engine';
import { loadSurface, toMapItems } from '../../map/items';
import type { MapItem } from '../../map/types';
import type { Pose } from '../../scene3d/freecam';
import { planToScene, sceneToPlan } from '../../scene3d/planNavigation';
import type { Flat, World } from '../../scene3d/types';
import { IconClose, UiIcon } from '../icons';

const noop = () => {};

/** Тот же движок и артефакты, что на вкладке «План», с выбором точки камеры. */
export function ScenePlanMap({
  runId,
  hasPlan,
  basemap,
  surfaceMeta,
  world,
  pose,
  onTeleport,
  onClose,
}: {
  runId: string;
  hasPlan: boolean;
  basemap: BasemapJson | null;
  surfaceMeta: SurfaceMeta | null;
  world: World;
  pose: Pose | null;
  onTeleport: (point: Flat) => void;
  onClose: () => void;
}) {
  const root = useRef<HTMLElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const engine = useRef<PlanEngine | null>(null);
  const navigate = useRef(onTeleport);
  const plan = useArtifact<PlanJson>(runId, 'plan.json', hasPlan);
  const [orientation, setOrientation] = useState<'street' | 'north'>('street');
  const items = useMemo(() => {
    if (plan.data) return toMapItems(plan.data);
    // Старые прогоны могут содержать только scene.json.
    const placements: MapItem[] = world.plants
      .filter((p) => !p.existing)
      .map((p, i) => ({
        ...sceneToPlan(p, world.origin),
        kind: 'placement',
        id: p.id,
        number: p.number ?? i + 1,
        planting_type: p.type,
        radius: p.species.crown_diameter_m / 2,
        verdict: 'allowed',
        species_code: p.code,
        species_ru: p.name,
        explanation: '',
        value: null,
        checks: [],
      }));
    return { placements, rejections: [] };
  }, [plan.data, world]);

  useEffect(() => {
    navigate.current = onTeleport;
  }, [onTeleport]);
  useEffect(() => {
    if (!canvas.current || !root.current) return;
    const created = new PlanEngine(canvas.current, root.current, {
      select: noop,
      probe: noop,
      move: noop,
      remove: noop,
      viewChanged: noop,
      placingChanged: noop,
      ambiguous: noop,
      navigate: (x, y) => {
        navigate.current(planToScene(x, y, world.origin));
      },
    });
    engine.current = created;
    return () => {
      created.destroy();
      engine.current = null;
    };
  }, [world.origin]);
  useEffect(() => {
    if (basemap) engine.current?.setBasemap(basemap);
  }, [basemap]);
  useEffect(() => {
    engine.current?.setPlan(items.placements, items.rejections);
    setOrientation(engine.current?.orientation() ?? 'street');
  }, [items]);
  useEffect(() => {
    engine.current?.setLawns(plan.data?.lawns ?? []);
  }, [plan.data]);
  useEffect(() => {
    engine.current?.setViewpoint(
      pose ? { ...sceneToPlan(pose, world.origin), yaw: pose.yaw } : null,
    );
  }, [pose, world.origin]);
  useEffect(() => {
    if (!surfaceMeta) return;
    let alive = true;
    void loadSurface(runId, surfaceMeta).then((image) => {
      if (alive) engine.current?.setSurface(image);
    });
    return () => {
      alive = false;
    };
  }, [runId, surfaceMeta]);

  return (
    <section ref={root} className="scene-plan-map" aria-label="Схема участка для перехода в 3D">
      <div className="scene-plan-head">
        <div className="scene-plan-title">
          <UiIcon name="plan" />
          <strong>Схема участка</strong>
          <span id="scene-plan-help">Нажмите на план, чтобы перейти в эту точку</span>
        </div>
        <div className="scene-plan-actions">
          <button
            type="button"
            aria-pressed={orientation === 'north'}
            onClick={() => {
              engine.current?.toggleOrientation();
              setOrientation(engine.current?.orientation() ?? 'street');
            }}
          >
            <UiIcon name="northUp" />
            {orientation === 'north' ? 'Север вверх' : 'Вдоль улицы'}
          </button>
          <button type="button" aria-label="Закрыть схему" onClick={onClose}>
            <IconClose />
          </button>
        </div>
      </div>
      <div className="scene-plan-canvas-holder">
        <canvas
          ref={canvas}
          onKeyDownCapture={(event) => {
            if (event.key === 'Escape') {
              event.stopPropagation();
              onClose();
            }
          }}
          tabIndex={0}
          aria-label="План участка. Перетаскивайте для перемещения, колесо для масштаба. Стрелки двигают план, Enter переносит в центр."
          aria-describedby="scene-plan-help"
        />
        <div className="scene-plan-center" aria-hidden="true" />
      </div>
      <div
        className="scene-plan-controls"
        data-map-obstacle="bottom"
        role="toolbar"
        aria-label="Масштаб схемы"
      >
        <button type="button" onClick={() => engine.current?.fit()}>
          <UiIcon name="fit" />
          Весь план
        </button>
        <button
          type="button"
          aria-label="Отдалить схему"
          onClick={() => engine.current?.zoomBy(1 / 1.4)}
        >
          <UiIcon name="minus" />
        </button>
        <button
          type="button"
          aria-label="Приблизить схему"
          onClick={() => engine.current?.zoomBy(1.4)}
        >
          <UiIcon name="plus" />
        </button>
        <span>Колесо — масштаб · перетаскивание — сдвиг</span>
      </div>
      {plan.isError ? (
        <p className="scene-plan-notice" role="status">
          План не загрузился. Показаны посадки из 3D-сцены.
        </p>
      ) : null}
    </section>
  );
}
