import { useEffect, useState } from 'react';

import type { RunOut } from '../../api/types';
import { aboutText, clockText } from '../../lib/format';

/** Ход расчёта - внизу по центру, привычное место строки состояния. Часы между опросами идут
 *  локально: секунды «прошло» и «осталось» тикают каждую секунду, а не раз в два опроса. */
export function ProgressHud({ run, fetchedAt }: { run: RunOut; fetchedAt: number }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => {
      setNow(Date.now());
    }, 1000);
    return () => {
      clearInterval(timer);
    };
  }, []);

  const progress = run.progress ?? null;
  const queued = run.state === 'queued';
  const title = queued ? 'В очереди' : progress?.title || 'Готовимся к расчёту';
  const pct = Math.round((progress?.fraction ?? 0) * 100);
  const steps = progress?.steps ?? [];
  const index = steps.findIndex((step) => step.state === 'active');
  const passed = Math.max(0, (now - fetchedAt) / 1000);
  const elapsed = progress
    ? progress.elapsed_s + passed
    : Math.max(0, (now - Date.parse(run.created_at)) / 1000);
  const eta = progress?.eta_s == null ? null : Math.max(progress.eta_s - passed, 0);

  return (
    <section className="hud hud-progress" data-map-obstacle="bottom" aria-label="Ход расчёта">
      <div className="progress-head">
        {/* Живая только строка этапа: часы тикают каждую секунду, и читалка иначе объявляла бы их. */}
        <p className="progress-title" aria-live="polite">
          {title}
        </p>
        <p className="progress-pct">{pct} %</p>
      </div>
      <div
        className="progress-bar"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={pct}
        aria-label="Ход расчёта"
      >
        <i style={{ width: `${String(pct)}%` }} />
      </div>
      <p className="progress-meta">
        <span>
          {index >= 0
            ? `этап ${String(index + 1)} из ${String(steps.length)}`
            : queued
              ? 'ждём свободного места'
              : ''}
        </span>
        <span>
          прошло {clockText(elapsed)}
          {eta == null ? '' : `, осталось ${aboutText(eta)}`}
        </span>
      </p>
    </section>
  );
}
