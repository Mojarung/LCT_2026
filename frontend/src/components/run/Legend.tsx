import { useEffect, useRef, type CSSProperties, type ReactNode } from 'react';

import { EXISTING_SHRUB, EXISTING_TREE, MODELS, type PlantModel } from '../../map/models';
import type { SwatchSign } from '../../map/signs';
import type { LayerKey } from '../../map/types';
import { useWorkspace } from '../../state/workspace';
import { IconClose } from '../icons';
import { ModelSwatch, SignSwatch } from './ModelSwatch';

/** Образец кустарника, пока в плане нет ни одного лиственного куста. */
const SHRUB_FALLBACK = 'syringa_vulgaris';

/** Образцы моделей для легенды: по одной на форму, которую человек встретит на плане.
 *  Кустарник - самый частый куст этого плана: образец обязан выглядеть как то, что на карте. */
const samples = (shrub: string | null): readonly [string, string][] => [
  ['tilia_cordata', 'лиственное дерево'],
  ['crataegus_laevigata', 'малое дерево в цвету'],
  ['pinus_sylvestris', 'хвойное дерево'],
  [shrub ?? SHRUB_FALLBACK, 'кустарник'],
  ['juniperus_sabina', 'хвойный кустарник'],
];

/** Знаки посадок инженерного стиля - формулировки легенд проектировщиков пилота
 *  (разбивочно-посадочный чертёж Грузинской, дендропланы Камчатской и Берзарина). */
const PLAN_SIGNS: readonly [SwatchSign, string][] = [
  ['tree', 'Проектируемое дерево (место посадки, контур кроны)'],
  ['conifer', 'Проектируемое хвойное дерево'],
  ['shrub', 'Проектируемый кустарник'],
  ['hedge', 'Живая изгородь, ряд кустарника'],
];

/** Существующие насаждения - знаки раздела «Существующие зеленые насаждения» шаблона
 *  заказчика. Сервис ничего не вырубает, поэтому все - сохраняемые. */
const EXISTING_LEGEND: readonly [SwatchSign, string][] = [
  ['existing-tree', 'Существующее древесное насаждение'],
  ['existing-conifer', 'Существующее хвойное насаждение'],
  ['existing-shrub', 'Существующее кустарниковое насаждение'],
  ['existing-hedge', 'Существующая живая изгородь, ширина условная'],
];

function Signs({ list }: { list: readonly [SwatchSign, string][] }) {
  return (
    <>
      {list.map(([sign, name]) => (
        <span key={sign}>
          <SignSwatch sign={sign} size={24} />
          <b>{name}</b>
        </span>
      ))}
    </>
  );
}

/** Слои результата в выходном DXF: то же, что на карте, но в CAD (writer.py). */
const DXF_LAYERS = [
  'GREEN_TREES',
  'GREEN_TREES_APPROVAL',
  'GREEN_TREES_BARRIER',
  'GREEN_SHRUBS',
  'GREEN_SHRUBS_APPROVAL',
  'GREEN_REJECT',
  'GREEN_LABELS',
  'GREEN_ZONE_ALLOWED',
  'GREEN_ZONE_APPROVAL',
  'GREEN_LAWN',
];

function Sample({ code, children }: { code: string; children: ReactNode }) {
  const model: PlantModel | undefined = MODELS.get(code);
  if (!model) return null;
  return (
    <span>
      <ModelSwatch model={model} modelKey={code} size={24} />
      <b>{children}</b>
    </span>
  );
}

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

/** Условные обозначения - своя панель у нижней кромки: их читают, глядя на карту, и они
 *  убираются одним движением. Галочка стоит у заголовка группы, обозначения - под ней: что
 *  нарисовано и чем это выключается - один и тот же список. */
export function Legend({
  done,
  shrub = null,
}: {
  done: boolean;
  /** Код самого частого лиственного кустарника плана (models.commonest). */
  shrub?: string | null;
}) {
  const open = useWorkspace((s) => s.panels.legend);
  const setLegend = useWorkspace((s) => s.setLegend);
  const drawing = useWorkspace((s) => s.mapStyle) === 'engineering';
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
            {/* Цвет кроны и знак - это вид, а виды со своими знаками перечислены в составе
                плана справа. Здесь только общие знаки: повторять список видов незачем. Вердикт
                показан кольцом: иначе два смысла спорили бы за один цвет. */}
            <div className={drawing ? 'legend legend-models legend-signs' : 'legend legend-models'}>
              {drawing ? (
                <Signs list={PLAN_SIGNS} />
              ) : (
                samples(shrub).map(([code, name]) => (
                  <Sample key={name} code={code}>
                    {name}
                  </Sample>
                ))
              )}
              <span>
                <i className="approval" />
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
              <i className="key barrier" /> Места, возможные с прикорневым барьером
            </LayerCheck>
            {/* Газоны плана - грунт, который посадки оставили свободным (слой GREEN_LAWN). */}
            <LayerCheck layer="lawns">Газоны плана</LayerCheck>
            <div className="legend">
              <span>
                <i className="swatch swatch-plan-lawn" />
                <b>{drawing ? 'газон сохраняемый' : 'сохраняемый или восстанавливаемый'}</b>
              </span>
              <span>
                <i className="swatch swatch-plan-lawn-new" />
                <b>{drawing ? 'газон устраиваемый' : 'устраиваемый'}</b>
              </span>
            </div>
            {/* Зоны допустимости - клетки, где дерево проходит все нормы (слои GREEN_ZONE_*):
                так видно, почему посадки стоят именно здесь, а не на соседнем газоне. */}
            <LayerCheck layer="zones">Зоны допустимости: дерево проходит все нормы</LayerCheck>
            <div className="legend">
              <span>
                <i className="swatch swatch-zone" />
                <b>допустимо</b>
              </span>
              <span>
                <i className="swatch swatch-zone-approval" />
                <b>на согласовании</b>
              </span>
            </div>
          </>
        ) : null}
        <LayerCheck layer="utilities">Подземные сети</LayerCheck>
        <div className="legend">
          {[
            ['--c-water', 'водопровод'],
            ['--c-sewer', 'канализация'],
            ['--c-storm', 'водосток'],
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
        {/* Газон и асфальт - это карта покрытий сервиса: по ней он решает, где грунт и можно
            сажать. Если посадка встала на площадку или асфальт, здесь это видно сразу. */}
        <LayerCheck layer="surfacemap">Газон и покрытия, как их понял сервис</LayerCheck>
        <div className="legend">
          <span>
            <i className="swatch swatch-lawn" />
            <b>газон: сажать можно</b>
          </span>
          <span>
            <i className="swatch swatch-asphalt" />
            <b>твёрдое покрытие</b>
          </span>
        </div>
        <LayerCheck layer="labels">Подписи покрытий с чертежа</LayerCheck>
        <LayerCheck layer="buildings">
          <i className="key swatch-building" /> Здания
        </LayerCheck>
        <LayerCheck layer="existing">
          {drawing ? 'Существующие насаждения' : 'Уже растёт на участке'}
        </LayerCheck>
        {drawing ? (
          <div className="legend legend-models legend-signs">
            <Signs list={EXISTING_LEGEND} />
          </div>
        ) : (
          <div className="legend legend-models">
            <span>
              <ModelSwatch
                model={EXISTING_TREE}
                modelKey="~existing-tree"
                look="existing"
                size={24}
              />
              <b>дерево по съёмке</b>
            </span>
            <span>
              <ModelSwatch
                model={EXISTING_SHRUB}
                modelKey="~existing-shrub"
                look="existing"
                size={24}
              />
              <b>кустарник по съёмке</b>
            </span>
          </div>
        )}
        {drawing ? null : (
          <div className="legend">
            <span>
              <i className="swatch" style={{ background: 'var(--c-existing)', height: 6 }} />
              <b>существующая кустарниковая полоса; ширина условная</b>
            </span>
          </div>
        )}
        {/* Раскрытие с «+», как остальные в панелях. Фраза про нетронутые исходные слои здесь
            повторяла штамп консоли и подсказку у «Скачать DXF» (жюри, итерация 7). */}
        <details className="legend-dxf fold">
          <summary>Слои результата в DXF</summary>
          <ul className="dxf-chips">
            {DXF_LAYERS.map((name) => (
              <li key={name}>{name}</li>
            ))}
          </ul>
        </details>
      </div>
    </aside>
  );
}
