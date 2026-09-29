import { useEffect, useState } from 'react';

import type { PlanEditor } from '../../state/editor';
import { useWorkspace } from '../../state/workspace';

/** Правка плана: сообщение и пересборка DXF. Режим включает кнопка «править» у карты (MapHud),
 *  по умолчанию он выключен: случайно сдвинуть дерево во время осмотра плана нельзя. Пока
 *  сказать нечего и пересобирать нечего, строки в пульте нет. */
export function EditBar({ editor, onRebuilt }: { editor: PlanEditor; onRebuilt: () => void }) {
  const stale = useWorkspace((s) => s.stale);
  const setStale = useWorkspace((s) => s.setStale);
  const message = useWorkspace((s) => s.message);
  const say = useWorkspace((s) => s.say);
  const [busy, setBusy] = useState(false);

  // Правки уже на сервере, но DXF и объяснения в файлах старые: закрыть вкладку в этот момент -
  // унести с собой план, который расходится с картой. Браузер спросит, уходить ли.
  useEffect(() => {
    if (!stale) return;
    const warn = (event: BeforeUnloadEvent) => {
      event.preventDefault();
    };
    window.addEventListener('beforeunload', warn);
    return () => {
      window.removeEventListener('beforeunload', warn);
    };
  }, [stale]);

  const rebuild = async () => {
    setBusy(true);
    say('Пересобираем DXF и объяснения, до минуты…');
    try {
      await editor.rebuild();
      setStale(false);
      say('Файлы результата пересобраны по исправленному плану.');
      onRebuilt();
    } catch (error) {
      say(error instanceof Error ? error.message : String(error), 'error');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      className="hud-foot"
      id="edit-bar"
      data-stale={stale ? '1' : '0'}
      data-empty={message.text || stale || busy ? '0' : '1'}
    >
      {/* Живая область в разметке всегда: читалка объявляет только изменения в области,
          существовавшей до сообщения. */}
      <p className="edit-message" role="status" aria-live="polite" data-kind={message.kind}>
        {message.text}
      </p>
      {/* Кнопка появляется, когда есть что пересобирать: без правок она обещала действие,
          которое ничего не меняет, и занимала строку пульта. */}
      {stale || busy ? (
        <button
          type="button"
          className="primary small"
          id="rebuild"
          disabled={busy}
          onClick={() => void rebuild()}
        >
          {busy ? 'Пересобираем…' : 'Пересобрать DXF'}
        </button>
      ) : null}
    </div>
  );
}
