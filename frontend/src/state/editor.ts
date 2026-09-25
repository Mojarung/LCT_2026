/* Правка плана на карте: живая проверка точки, перенос, удаление, пересборка DXF.
 *
 * Вердикт и трасса правил после переноса берутся у сервиса, а не досочиняются на клиенте.
 * Правки идут строго по очереди (EditQueue). Пересборка считается законченной, только когда
 * прогон вернулся в «готов» с новой отметкой времени: ответ 202 означает «принято», а не
 * «сделано», и старый интерфейс писал «пересобраны» до начала работы. */

import { getJson, postJson } from '../api/client';
import type { RuleCheck } from '../api/artifacts';
import type { CheckOut, PlanSummaryOut, RunOut } from '../api/types';
import type { MapItem } from '../map/types';
import { EditQueue } from './editQueue';
import { useWorkspace } from './workspace';

const REBUILD_POLL_MS = 1500;
const REBUILD_LIMIT_MS = 10 * 60_000;

const reason = (error: unknown): string => (error instanceof Error ? error.message : String(error));

const sleep = (ms: number) =>
  new Promise<void>((resolve) => {
    setTimeout(resolve, ms);
  });

export interface EditorHost {
  /** Вердикт под курсором во время переноса. */
  dragVerdict(verdict: string | null): void;
  /** Отметки изменились на месте: перерисовать. */
  itemsChanged(): void;
  /** Посадка удалена из плана. */
  removed(item: MapItem): void;
}

export class PlanEditor {
  private readonly queue = new EditQueue();
  private ticket = 0;
  private host: EditorHost | null = null;

  constructor(private readonly runId: string) {}

  /** Страница подключает карту после монтирования: редактор живёт дольше отрисовки и не
   *  держит ссылок на компоненты. Возвращает отключение. */
  attach(host: EditorHost): () => void {
    this.host = host;
    return () => {
      if (this.host === host) this.host = null;
    };
  }

  private url(path: string): string {
    return `/api/v1/runs/${encodeURIComponent(this.runId)}/${path}`;
  }

  private check(item: MapItem, x: number, y: number): Promise<CheckOut> {
    return postJson<CheckOut>(this.url('check'), { x, y, species: item.species_code ?? null });
  }

  /** Живой вердикт под курсором. Ответ приходит с задержкой, поэтому устаревшие ответы
   *  отбрасываются по номеру запроса - иначе кружок мигает чужим цветом. */
  async probe(item: MapItem, x: number, y: number): Promise<void> {
    const ticket = ++this.ticket;
    try {
      const result = await this.check(item, x, y);
      if (ticket === this.ticket)
        this.host?.dragVerdict(result.plantable ? result.verdict : 'rejected');
    } catch (error) {
      if (ticket === this.ticket) useWorkspace.getState().say(reason(error), 'error');
    }
  }

  move(item: MapItem, x: number, y: number): Promise<void> {
    this.ticket += 1; // ответы проб, пришедшие после отпускания, больше не нужны
    return this.queue.enqueue(async () => {
      const store = useWorkspace.getState();
      try {
        const summary = await postJson<PlanSummaryOut>(this.url('edits'), {
          edits: [{ kind: 'move', placement_id: item.id, x, y }],
        });
        const result = await this.check(item, x, y);
        item.verdict = result.plantable ? result.verdict : 'rejected';
        item.checks = (result.checks ?? []).map((c): RuleCheck => ({
          rule_id: c.rule_id,
          outcome: c.outcome,
          measured_m: c.measured_m ?? null,
          threshold_m: c.threshold_m ?? null,
          object_class: c.object_class ?? null,
        }));
        item.explanation = '';
        // Ценность считается по плану целиком: после переноса она известна только после пересборки.
        item.value = null;
        item.note = result.note;
        this.host?.itemsChanged();
        store.setStale(summary.stale);
        store.touch();
        store.say(`Посадка №${item.number} перенесена. Нормы пересчитаны.`);
      } catch (error) {
        store.say(reason(error), 'error');
      }
    });
  }

  remove(item: MapItem): Promise<void> {
    return this.queue.enqueue(async () => {
      const store = useWorkspace.getState();
      try {
        const summary = await postJson<PlanSummaryOut>(this.url('edits'), {
          edits: [{ kind: 'delete', placement_id: item.id }],
        });
        this.host?.removed(item);
        store.select(null);
        store.setStale(summary.stale);
        store.say(`Посадка №${item.number} удалена. В плане осталось ${summary.placements}.`);
      } catch (error) {
        store.say(reason(error), 'error');
      }
    });
  }

  /** Пересобрать DXF и объяснения. Ждёт правки, ушедшие раньше, и конца самой пересборки. */
  rebuild(): Promise<RunOut> {
    return this.queue.enqueue(async () => {
      const before = await getJson<RunOut>(this.url('').replace(/\/$/, ''), { cache: 'no-store' });
      await postJson<PlanSummaryOut>(this.url('rebuild'), {});
      const deadline = Date.now() + REBUILD_LIMIT_MS;
      while (Date.now() < deadline) {
        await sleep(REBUILD_POLL_MS);
        const run = await getJson<RunOut>(this.url('').replace(/\/$/, ''), { cache: 'no-store' });
        if (run.state === 'failed') throw new Error(run.error ?? 'Пересборка не удалась.');
        if (run.state === 'succeeded' && run.updated_at !== before.updated_at) return run;
      }
      throw new Error('Пересборка идёт дольше десяти минут: проверьте, что сервис жив.');
    });
  }
}
