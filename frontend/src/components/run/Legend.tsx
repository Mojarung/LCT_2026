import { useEffect, useRef, type CSSProperties, type ReactNode } from 'react';

import type { LayerKey } from '../../map/types';
import { useWorkspace } from '../../state/workspace';
import { IconClose } from '../icons';

function LayerCheck({ layer, children }: { layer: LayerKey; children: ReactNode }) {
  const on = useWorkspace((s) => s.layers[layer]);
  const setLayer = useWorkspace((s) => s.setLayer);
  return (
    <label className="check legend-group">
      <input
        type="checkbox"
        checked={on}
        onChange={(event) => {
          setLayer(layer, event.target.checked);
        }}
      />{' '}
      {children}
    </label>
  );
}

const line = (token: string): CSSProperties => ({ borderColor: `var(${token})` });
const dot = (token: string): CSSProperties => ({
  borderColor: `var(${token})`,
  background: `color-mix(in srgb, var(${token}) 33%, transparent)`,
});

/** Условные обозначения - своя панель у нижней кромки: их читают, глядя на карту, и они
 *  убираются одним движением. Галочка стоит у заголовка группы, обозначения - под ней: что
 *  нарисовано и чем это выключается - один и тот же список. */
export function Legend({ done }: { done: boolean }) {
  const open = useWorkspace((s) => s.panels.legend);
  const setLegend = useWorkspace((s) => s.setLegend);
  const box = useRef<HTMLElement>(null);

  // Пульт слева уступает место панели обозначений ровно на её высоту: высота зависит от
  // прогона и от окна, поэтому её меряет наблюдатель и кладёт в переменную рабочего места.
  useEffect(() => {
    const element = box.current;
    const workspace = element?.closest<HTMLElement>('.workspace');
    if (!element || !workspace) return;
    const measure = () => {
      workspace.style.setProperty(
        '--legend-h',
        `${String(Math.round(element.getBoundingClientRect().height))}px`,
      );
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => {
      observer.disconnect();
    };
  }, [open]);

  return (
    <aside
      className="hud hud-legend"
      id="legend"
      aria-label="Условные обозначения"
      data-map-obstacle="side"
      hidden={!open}
      ref={box}
    >
      <div className="legend-head">
        <h2 className="hud-label">Условные обозначения</h2>
        <button
          type="button"
          className="legend-hide"
          title="Скрыть обозначения"
          aria-label="Скрыть условные обозначения"
          onClick={() => {
            setLegend(false);
          }}
        >
          <IconClose />
        </button>
      </div>
      <div className="legend-scroll">
        {/* Сначала то, что посчитал сервис, потом подоснова: к карте приходят с вопросом «что
            здесь посадили», а цвет сетей читается и без подсказки. */}
        {done ? (
          <>
            <LayerCheck layer="placements">Посадки плана</LayerCheck>
            <div className="legend legend-plan">
              <span>
                <i className="dot" style={dot('--ok')} />
                <b>допускается</b>
              </span>
              <span>
                <i className="dot" style={dot('--warn')} />
                <b>требует согласования</b>
              </span>
            </div>
            <LayerCheck layer="weak">
              <i className="key tri" /> Слабые места: без посадки индекс заметно выше
            </LayerCheck>
            <LayerCheck layer="rejections">
              <i className="key cross" /> Отклонённые места
            </LayerCheck>
            <LayerCheck layer="barrier">
              <i className="key ring" /> Места, возможные с прикорневым барьером
            </LayerCheck>
          </>
        ) : null}
        <LayerCheck layer="utilities">Подземные сети</LayerCheck>
        <div className="legend">
          {[
            ['--c-water', 'водопровод'],
            ['--c-sewer', 'канализация'],
            ['--c-storm', 'ливневая'],
            ['--c-gas', 'газ'],
            ['--c-heat', 'теплосеть'],
            ['--c-power', 'силовой кабель'],
            ['--c-telecom', 'связь'],
          ].map(([token = '', name]) => (
            <span key={token}>
              <i style={line(token)} />
              <b>{name}</b>
            </span>
          ))}
          <span>
            <i className="dash" style={line('--c-overhead')} />
            <b>воздушная линия</b>
          </span>
        </div>
        <LayerCheck layer="surfaces">Борта и покрытия</LayerCheck>
        <div className="legend">
          <span>
            <i style={line('--c-curb')} />
            <b>борт</b>
          </span>
          <span>
            <i style={line('--c-pavement')} />
            <b>тротуар</b>
          </span>
          <span>
            <i style={line('--c-road')} />
            <b>проезжая часть</b>
          </span>
          <span>
            <i className="dash" style={line('--c-fence')} />
            <b>ограда</b>
          </span>
          <span>
            <i className="dash" style={line('--c-boundary')} />
            <b>граница работ</b>
          </span>
        </div>
        {/* Как сервис понял покрытия: по этой карте он решает, где грунт и можно сажать. Если
            посадка встала на площадку или асфальт, здесь это видно сразу. */}
        <LayerCheck layer="surfacemap">Покрытия, как их понял сервис</LayerCheck>
        <div className="legend">
          <span>
            <i className="swatch" style={{ background: 'rgba(104, 158, 104, .55)' }} />
            <b>грунт: сажать можно</b>
          </span>
          <span>
            <i className="swatch" style={{ background: 'rgba(140, 142, 150, .6)' }} />
            <b>твёрдое покрытие</b>
          </span>
        </div>
        <LayerCheck layer="labels">Подписи покрытий с чертежа</LayerCheck>
        <LayerCheck layer="buildings">
          <i className="key" style={line('--c-building')} /> Здания
        </LayerCheck>
        <LayerCheck layer="existing">
          <i className="key dot" style={line('--c-existing')} /> Существующие деревья
        </LayerCheck>
      </div>
    </aside>
  );
}
