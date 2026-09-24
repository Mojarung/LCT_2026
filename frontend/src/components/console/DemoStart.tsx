import { useState } from 'react';
import { useNavigate } from 'react-router';

import { postJson } from '../../api/client';
import type { RunOut } from '../../api/types';

/** Встроенный фрагмент нужен там, где датасета нет: на стенде без каталога улиц иначе нечего
 *  запустить. Когда улицы есть, он только отнимает у формы первое место. */
export function DemoStart() {
  const navigate = useNavigate();
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');

  const start = async () => {
    setBusy(true);
    setMessage('');
    try {
      const run = await postJson<RunOut>('/api/v1/runs/demo', {});
      void navigate(`/runs/${run.id}`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
      setBusy(false);
    }
  };

  return (
    <div className="start-row">
      <div>
        <p className="start-title">Встроенный участок улицы Берзарина</p>
        <p className="hint">Фрагмент настоящей подосновы с сетями: каталог улиц не подключён.</p>
        <p className="form-error" role="status" aria-live="polite">
          {message}
        </p>
      </div>
      <button type="button" className="ghost" disabled={busy} onClick={() => void start()}>
        {busy ? 'Запускаем…' : 'Запустить на встроенном участке'}
      </button>
    </div>
  );
}
