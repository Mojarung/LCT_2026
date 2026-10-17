import type { ReactNode } from 'react';

import { useEngine } from '../../state/engine';
import { useWorkspace } from '../../state/workspace';
import { UiIcon } from '../icons';

/** Переключатель из двух вариантов: оба названы, выбранный нажат. Одна кнопка с подписью
 *  текущего состояния («по улице») читалась то как состояние, то как действие. */
function Pair<T extends string>({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: T;
  options: readonly [T, string, string][];
  onChange: (value: T) => void;
}) {
  return (
    <span className="hud-pair" role="group" aria-label={label}>
      {options.map(([key, text, title]) => (
        <button
          key={key}
          type="button"
          aria-pressed={value === key}
          title={title}
          onClick={() => {
            if (value !== key) onChange(key);
          }}
        >
          {text}
        </button>
      ))}
    </span>
  );
}

function Sep(): ReactNode {
  return <i className="hud-sep" aria-hidden="true" />;
}

/** Кнопки карты у нижней кромки, по центру свободной области. Колесо мыши есть не у всех: на
 *  ноутбуке тачпадом масштаб ловится плохо, а на защите карту крутят чужими руками - ползунок
 *  задаёт масштаб сразу. Правка плана - здесь же, у карты, которую она меняет. */
export function MapHud({ editable = false }: { editable?: boolean }) {
  const engine = useEngine();
  const share = useWorkspace((s) => s.zoomShare);
  const orientation = useWorkspace((s) => s.orientation);
  const setOrientation = useWorkspace((s) => s.setOrientation);
  const legend = useWorkspace((s) => s.panels.legend);
  const setLegend = useWorkspace((s) => s.setLegend);
  const mapStyle = useWorkspace((s) => s.mapStyle);
  const setMapStyle = useWorkspace((s) => s.setMapStyle);
  const editing = useWorkspace((s) => s.editing);
  const setEditing = useWorkspace((s) => s.setEditing);
  return (
    <>
      {/* Как показан план - в углу карты, отдельно от кнопок действия внизу: две пары
          вариантов в полосе не помещались между панелями на ноутбучной ширине. */}
      <div className="hud hud-view" role="group" aria-label="Вид карты" data-map-obstacle="top">
        <Pair
          label="Поворот плана"
          value={orientation}
          options={[
            ['street', 'Вдоль улицы', 'Улица горизонтально'],
            ['north', 'Север вверх', 'Север вверху, как на топосъёмке'],
          ]}
          onChange={() => {
            const current = engine.current;
            if (!current) return;
            current.toggleOrientation();
            setOrientation(current.orientation());
          }}
        />
        {/* Инженерный чертёж - знаки дендроплана, привычные проектировщику и проверяющему;
            иллюстрация - кроны моделей видов, как на слайдах. */}
        <Pair
          label="Стиль карты"
          value={mapStyle}
          options={[
            ['engineering', 'Чертёж', 'Условные знаки дендроплана'],
            ['illustrated', 'Кроны', 'Иллюстрация: кроны моделей видов'],
          ]}
          onChange={setMapStyle}
        />
      </div>
      <div className="hud hud-bottom" data-map-obstacle="bottom" role="toolbar" aria-label="Карта">
        <button
          type="button"
          className="hud-fit"
          title="Вписать весь план в окно"
          onClick={() => {
            engine.current?.fit();
          }}
        >
          <UiIcon name="fit" />
          <span className="hud-text">Весь план</span>
        </button>
        <span className="hud-zoom">
          <button
            type="button"
            className="hud-icon"
            title="Отдалить"
            aria-label="Отдалить"
            onClick={() => {
              engine.current?.zoomBy(1 / 1.4);
            }}
          >
            <UiIcon name="minus" />
          </button>
          <input
            type="range"
            id="zoom-range"
            min={0}
            max={1000}
            step={1}
            value={Math.round(share * 1000)}
            title="Масштаб"
            aria-label="Масштаб карты"
            onChange={(event) => {
              engine.current?.setZoomShare(Number(event.target.value) / 1000);
            }}
          />
          <button
            type="button"
            className="hud-icon"
            title="Приблизить"
            aria-label="Приблизить"
            onClick={() => {
              engine.current?.zoomBy(1.4);
            }}
          >
            <UiIcon name="plus" />
          </button>
        </span>
        <Sep />
        <button
          type="button"
          aria-pressed={legend}
          aria-controls="legend"
          title="Показать или скрыть условные обозначения и слои"
          onClick={() => {
            setLegend(!legend);
          }}
        >
          <UiIcon name="layers" />
          <span className="hud-text">Легенда</span>
        </button>
        {editable ? (
          <button
            type="button"
            className="hud-edit"
            aria-pressed={editing}
            title="Переносить и удалять посадки на карте"
            onClick={() => {
              setEditing(!editing);
            }}
          >
            <UiIcon name="edit" />
            <span className="hud-text">Править</span>
          </button>
        ) : null}
      </div>
    </>
  );
}
