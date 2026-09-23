import { useEffect, useRef, type RefObject } from 'react';

import { PlanEngine } from '../../map/engine';
import type { EngineHooks } from '../../map/types';
import { useEngine } from '../../state/engine';

/** Холст карты. Движок создаётся один раз на монтирование и уничтожается в очистке: StrictMode
 *  в разработке монтирует эффекты дважды, и движок обязан снять все свои обработчики. */
export function PlanMap({
  root,
  hooks,
  interactive,
}: {
  root: RefObject<HTMLElement | null>;
  hooks: RefObject<EngineHooks>;
  interactive: boolean;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const engineRef = useEngine();

  useEffect(() => {
    if (!canvasRef.current || !root.current) return;
    // Хуки читаются через ссылку: страница меняет их при каждой отрисовке, а движок живёт дольше.
    const created = new PlanEngine(canvasRef.current, root.current, {
      select: (item) => {
        hooks.current.select(item);
      },
      probe: (item, x, y) => {
        hooks.current.probe(item, x, y);
      },
      move: (item, x, y) => {
        hooks.current.move(item, x, y);
      },
      remove: (item) => {
        hooks.current.remove(item);
      },
      viewChanged: () => {
        hooks.current.viewChanged();
      },
    });
    engineRef.current = created;
    return () => {
      created.destroy();
      if (engineRef.current === created) engineRef.current = null;
    };
  }, [engineRef, hooks, root]);

  return (
    <canvas
      id="plan-canvas"
      ref={canvasRef}
      tabIndex={interactive ? 0 : -1}
      aria-label="План посадок на подоснове чертежа. Стрелками выбирают посадку, Enter центрирует её."
    />
  );
}
