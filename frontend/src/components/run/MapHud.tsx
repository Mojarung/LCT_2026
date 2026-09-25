import { useEngine } from '../../state/engine';
import { useWorkspace } from '../../state/workspace';

/** Кнопки карты у нижней кромки. Колесо мыши есть не у всех: на ноутбуке тачпадом масштаб
 *  ловится плохо, а на защите карту крутят чужими руками - ползунок задаёт масштаб сразу. */
export function MapHud() {
  const engine = useEngine();
  const share = useWorkspace((s) => s.zoomShare);
  const orientation = useWorkspace((s) => s.orientation);
  const setOrientation = useWorkspace((s) => s.setOrientation);
  const legend = useWorkspace((s) => s.panels.legend);
  const setLegend = useWorkspace((s) => s.setLegend);
  return (
    <div className="hud hud-bottom" data-map-obstacle="bottom">
      <button
        type="button"
        title="Показать весь план"
        onClick={() => {
          engine.current?.fit();
        }}
      >
        весь план
      </button>
      <button
        type="button"
        title="Отдалить"
        aria-label="Отдалить"
        onClick={() => {
          engine.current?.zoomBy(1 / 1.4);
        }}
      >
        −
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
        title="Приблизить"
        aria-label="Приблизить"
        onClick={() => {
          engine.current?.zoomBy(1.4);
        }}
      >
        +
      </button>
      <button
        type="button"
        aria-pressed={orientation === 'street'}
        title="Развернуть вид вдоль улицы или по северу"
        onClick={() => {
          const current = engine.current;
          if (!current) return;
          current.toggleOrientation();
          setOrientation(current.orientation());
        }}
      >
        {orientation === 'street' ? 'по улице' : 'по северу'}
      </button>
      <button
        type="button"
        aria-pressed={legend}
        title="Показать или скрыть условные обозначения"
        onClick={() => {
          setLegend(!legend);
        }}
      >
        обозначения
      </button>
    </div>
  );
}
