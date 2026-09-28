import { useEffect, useState } from 'react';

import type { PlanEditor } from '../../state/editor';
import { useWorkspace } from '../../state/workspace';

/** Правка плана: переключатель режима, сообщение и пересборка DXF. Режим правки выключен по
 *  умолчанию: случайно сдвинуть дерево во время осмотра плана не должно быть возможно. */
export function EditBar({ editor, onRebuilt }: { editor: PlanEditor; onRebuilt: () => void }) {
  const editing = useWorkspace((s) => s.editing);
  const setEditing = useWorkspace((s) => s.setEditing);
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
    <div className="hud-foot" id="edit-bar" data-stale={stale ? '1' : '0'}>
      <label className="check">
        <input
          type="checkbox"
          checked={editing}
          onChange={(event) => {
            setEditing(event.target.checked);
          }}
        />
        Переносить и удалять посадки
      </label>
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
