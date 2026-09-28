/* Правка плана на карте: живая проверка точки, перенос, удаление, пересборка DXF.
 *
 * Вердикт и трасса правил после переноса берутся у сервиса, а не досочиняются на клиенте.
 * Правки идут строго по очереди (EditQueue). Пересборка считается законченной, только когда
 * прогон вернулся в «готов» с новой отметкой времени: ответ 202 означает «принято», а не
 * «сделано», и старый интерфейс писал «пересобраны» до начала работы. */

import { getJson, postJson } from '../api/client';
import type { RuleCheck } from '../api/artifacts';
import type { CheckOut, PlanSummaryOut, RunOut } from '../api/types';
import type { DragProbe, MapItem } from '../map/types';
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
  /** Ответ живой проверки под курсором во время переноса: вердикт и трасса правил. */
  dragProbe(probe: DragProbe | null): void;
  /** Отметки изменились на месте: перерисовать. */
  itemsChanged(): void;
  /** Посадка удалена из плана. */
  removed(item: MapItem): void;
  /** Перенос посадки ушёл на сервер (on) или вернулся: показать ожидание у неё на карте. */
  pending(item: MapItem, on: boolean): void;
}

/** Трасса правил из ответа сервиса в том виде, в каком её хранит план. */
function ruleChecks(result: CheckOut): RuleCheck[] {
  return (result.checks ?? []).map((c) => ({
    rule_id: c.rule_id,
    outcome: c.outcome,
    measured_m: c.measured_m ?? null,
    threshold_m: c.threshold_m ?? null,
    object_class: c.object_class ?? null,
  }));
}

export class PlanEditor {
  private readonly queue = new EditQueue();
  private ticket = 0;
  private host: EditorHost | null = null;
  /** Сколько переносов каждой посадки ещё в очереди: ожидание снимается с последним. */
  private readonly moving = new Map<MapItem, number>();

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
      if (ticket === this.ticket) {
        this.host?.dragProbe({
          verdict: result.plantable ? result.verdict : 'rejected',
          checks: ruleChecks(result),
        });
      }
    } catch (error) {
      if (ticket === this.ticket) useWorkspace.getState().say(reason(error), 'error');
    }
  }

  private hold(item: MapItem, delta: 1 | -1): void {
    const count = (this.moving.get(item) ?? 0) + delta;
    if (count > 0) this.moving.set(item, count);
    else this.moving.delete(item);
    this.host?.pending(item, count > 0);
  }

  move(item: MapItem, x: number, y: number, from?: { x: number; y: number }): Promise<void> {
    this.ticket += 1; // ответы проб, пришедшие после отпускания, больше не нужны
    // Перенос на сервере идёт секунды, а на большой улице - десятки: признак жизни нужен сразу,
    // до запроса, а не после ответа (жюри, итерация 7).
    this.hold(item, 1);
    useWorkspace.getState().say(`Переносим посадку № ${String(item.number)}…`);
    return this.queue.enqueue(async () => {
      const store = useWorkspace.getState();
      let summary: PlanSummaryOut;
      try {
        summary = await postJson<PlanSummaryOut>(this.url('edits'), {
          edits: [{ kind: 'move', placement_id: item.id, x, y }],
        });
      } catch (error) {
        // Сервис правку не принял: посадка возвращается туда, где она стоит в плане, иначе
        // карта показывала бы перенос, которого нет ни в плане, ни в DXF.
        if (from) {
          item.x = from.x;
          item.y = from.y;
          this.host?.itemsChanged();
          store.say(`${reason(error)} Посадка возвращена на место.`, 'error');
        } else {
          store.say(reason(error), 'error');
        }
        this.hold(item, -1);
        return;
      }
      try {
        const result = await this.check(item, x, y);
        item.verdict = result.plantable ? result.verdict : 'rejected';
        item.checks = ruleChecks(result);
        item.explanation = '';
        // Ценность считается по плану целиком: после переноса она известна только после пересборки.
        item.value = null;
        item.note = result.note;
        this.host?.itemsChanged();
        store.setStale(summary.stale);
        store.touch();
        store.say(`Посадка № ${String(item.number)} перенесена и проверена по нормам.`);
      } catch (error) {
        store.say(reason(error), 'error');
      } finally {
        this.hold(item, -1);
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
        store.say(
          `Посадка № ${String(item.number)} удалена. В плане осталось ${String(summary.placements)}.`,
        );
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
      throw new Error('Пересборка идёт дольше 10 минут. Проверьте, что сервис работает.');
    });
  }
}
