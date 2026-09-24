import { useState } from 'react';
import { useNavigate } from 'react-router';

import { postJson } from '../../api/client';
import type { RunOut } from '../../api/types';

/** Встроенный фрагмент нужен там, где датасета нет: на стенде без каталога улиц иначе нечего
 *  запустить. Форма ставит его на место каталога и делает главной кнопкой, пока не выбран
 *  свой чертёж. */
export function useDemoStart() {
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

  return { start, busy, message };
}
