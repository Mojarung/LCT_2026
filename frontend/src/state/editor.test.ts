import { afterEach, describe, expect, it, vi } from 'vitest';

import type { MapItem } from '../map/types';
import { mockApi, run, type Call } from '../test/api';
import { PlanEditor } from './editor';
import { useWorkspace } from './workspace';

const item = (): MapItem => ({
  kind: 'placement',
  id: 'p1',
  number: 7,
  planting_type: 'tree',
  x: 10,
  y: 20,
  radius: 2,
  verdict: 'allowed',
  species_code: 'tilia_cordata',
  species_ru: 'Липа мелколистная',
  explanation: 'Посадка №7 допускается.',
  value: { delta: 0.001, percentile: 50, by_term: {}, reasons: [], weak: [] },
  checks: [],
});

/** Тело запроса: клиент шлёт JSON строкой. */
const bodyOf = (call: Call | undefined): unknown => JSON.parse(call?.init?.body as string);

const summary = { allowed: 2, needs_approval: 1, placements: 3, rejections: 0, stale: true };

function deferred<T>() {
  let resolve: (value: T) => void = () => undefined;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

afterEach(() => {
  vi.useRealTimers();
});

describe('PlanEditor.move', () => {
  it('takes the verdict and the rule trace from the service, not from the client', async () => {
    const calls = mockApi({
      'POST /api/v1/runs/r1/edits': summary,
      'POST /api/v1/runs/r1/check': {
        plantable: true,
        verdict: 'needs_approval',
        note: 'Ближе нормы к силовому кабелю: нужна защита корней.',
        checks: [
          {
            rule_id: 'R-UTIL-POWER-001',
            outcome: 'fail',
            measured_m: 1.4,
            threshold_m: 2,
            object_class: 'power',
          },
        ],
      },
    });
    const moved = item();
    const host = { dragProbe: vi.fn(), itemsChanged: vi.fn(), removed: vi.fn(), pending: vi.fn() };
    const editor = new PlanEditor('r1');
    editor.attach(host);

    await editor.move(moved, 12.5, 21);

    const edit = calls.find((c) => c.url.endsWith('/edits'));
    expect(bodyOf(edit)).toEqual({
      edits: [{ kind: 'move', placement_id: 'p1', x: 12.5, y: 21 }],
    });
    const check = calls.find((c) => c.url.endsWith('/check'));
    expect(bodyOf(check)).toEqual({
      x: 12.5,
      y: 21,
      species: 'tilia_cordata',
    });
    expect(moved.verdict).toBe('needs_approval');
    expect(moved.checks).toEqual([
      {
        rule_id: 'R-UTIL-POWER-001',
        outcome: 'fail',
        measured_m: 1.4,
        threshold_m: 2,
        object_class: 'power',
      },
    ]);
    // Ценность и текст выгрузки после переноса неизвестны до пересборки: старые не показываем.
    expect(moved.value).toBeNull();
    expect(moved.explanation).toBe('');
    expect(moved.note).toBe('Ближе нормы к силовому кабелю: нужна защита корней.');
    expect(host.itemsChanged).toHaveBeenCalledOnce();
    const state = useWorkspace.getState();
    expect(state.stale).toBe(true);
    expect(state.message).toEqual({
      text: 'Посадка № 7 перенесена. Нормы пересчитаны.',
      kind: 'info',
    });
    expect(host.pending.mock.calls).toEqual([
      [moved, true],
      [moved, false],
    ]);
  });

  it('says the move has started and keeps the waiting ring until the service answers', async () => {
    const edits = deferred<Response>();
    mockApi({
      'POST /api/v1/runs/r1/edits': () => edits.promise,
      'POST /api/v1/runs/r1/check': { plantable: true, verdict: 'allowed', note: '', checks: [] },
    });
    const host = { dragProbe: vi.fn(), itemsChanged: vi.fn(), removed: vi.fn(), pending: vi.fn() };
    const editor = new PlanEditor('r1');
    editor.attach(host);
    const moved = item();

    const done = editor.move(moved, 3, 4);
    // До ответа сервиса: сообщение о начале и кольцо ожидания, снимать его рано.
    expect(useWorkspace.getState().message).toEqual({
      text: 'Переносим посадку № 7…',
      kind: 'info',
    });
    expect(host.pending.mock.calls).toEqual([[moved, true]]);

    edits.resolve(Response.json(summary));
    await done;
    expect(host.pending.mock.calls).toEqual([
      [moved, true],
      [moved, false],
    ]);
    expect(useWorkspace.getState().message.text).toBe('Посадка № 7 перенесена. Нормы пересчитаны.');
  });

  it('drops the waiting ring when the service refuses the move', async () => {
    mockApi({
      'POST /api/v1/runs/r1/edits': () =>
        Response.json(
          { title: 'Conflict', status: 409, detail: 'Прогон ещё считается.' },
          { status: 409, headers: { 'content-type': 'application/problem+json' } },
        ),
    });
    const host = { dragProbe: vi.fn(), itemsChanged: vi.fn(), removed: vi.fn(), pending: vi.fn() };
    const editor = new PlanEditor('r1');
    editor.attach(host);
    const moved = item();

    await editor.move(moved, 1, 2);
    expect(host.pending.mock.calls).toEqual([
      [moved, true],
      [moved, false],
    ]);
  });

  it('marks a point the service will not plant as rejected', async () => {
    mockApi({
      'POST /api/v1/runs/r1/edits': summary,
      'POST /api/v1/runs/r1/check': { plantable: false, verdict: 'allowed', note: '', checks: [] },
    });
    const moved = item();
    await new PlanEditor('r1').move(moved, 1, 2);
    expect(moved.verdict).toBe('rejected');
  });

  it('reports a refused edit and leaves the plan as it was', async () => {
    mockApi({
      'POST /api/v1/runs/r1/edits': () =>
        Response.json(
          { title: 'Conflict', status: 409, detail: 'Прогон ещё считается.' },
          { status: 409, headers: { 'content-type': 'application/problem+json' } },
        ),
    });
    const moved = item();
    await new PlanEditor('r1').move(moved, 1, 2);
    expect(moved.verdict).toBe('allowed');
    expect(useWorkspace.getState().message).toEqual({
      text: 'Прогон ещё считается.',
      kind: 'error',
    });
  });
});

describe('PlanEditor.probe', () => {
  it('drops an answer that arrives after a newer probe', async () => {
    const first = deferred<Response>();
    const second = deferred<Response>();
    const answers = [first.promise, second.promise];
    const calls = mockApi({
      'POST /api/v1/runs/r1/check': () => answers.shift() ?? Response.error(),
    });
    const host = { dragProbe: vi.fn(), itemsChanged: vi.fn(), removed: vi.fn(), pending: vi.fn() };
    const editor = new PlanEditor('r1');
    editor.attach(host);

    const older = editor.probe(item(), 1, 1);
    const newer = editor.probe(item(), 2, 2);
    const cable = {
      rule_id: 'R-UTIL-POWER-001',
      outcome: 'fail',
      measured_m: 1.2,
      threshold_m: 2,
      object_class: 'utility.power_cable',
    };
    second.resolve(
      Response.json({ plantable: true, verdict: 'needs_approval', note: '', checks: [cable] }),
    );
    await newer;
    first.resolve(Response.json({ plantable: false, verdict: 'allowed', note: '', checks: [] }));
    await older;

    // Вердикт красит кольцо, трасса правил даёт выноски у перетаскиваемой посадки.
    expect(host.dragProbe.mock.calls).toEqual([[{ verdict: 'needs_approval', checks: [cable] }]]);
    // Проверяется точка под курсором, а не прежнее место посадки.
    expect(calls.map((c) => bodyOf(c))).toEqual([
      { x: 1, y: 1, species: 'tilia_cordata' },
      { x: 2, y: 2, species: 'tilia_cordata' },
    ]);
  });
});

describe('PlanEditor.remove', () => {
  it('drops the placement and says how many are left', async () => {
    mockApi({ 'POST /api/v1/runs/r1/edits': { ...summary, placements: 2 } });
    const host = { dragProbe: vi.fn(), itemsChanged: vi.fn(), removed: vi.fn(), pending: vi.fn() };
    const editor = new PlanEditor('r1');
    editor.attach(host);
    const gone = item();
    useWorkspace.getState().select(gone);

    await editor.remove(gone);

    expect(host.removed).toHaveBeenCalledWith(gone);
    expect(useWorkspace.getState().selected).toBeNull();
    expect(useWorkspace.getState().message.text).toBe('Посадка № 7 удалена. В плане осталось 2.');
  });
});

describe('PlanEditor.rebuild', () => {
  it('waits until the run is back with a new timestamp, not for the 202', async () => {
    vi.useFakeTimers();
    const answers = [
      run({ state: 'succeeded', updated_at: 'T0' }), // до пересборки
      run({ state: 'succeeded', updated_at: 'T0' }), // сервис ещё не взял задачу
      run({ state: 'running', updated_at: 'T0' }),
      run({ state: 'succeeded', updated_at: 'T1' }),
    ];
    mockApi({
      '/api/v1/runs/r1': () => Response.json(answers.shift()),
      'POST /api/v1/runs/r1/rebuild': summary,
    });
    let finished = false;
    const pending = new PlanEditor('r1').rebuild().then((result) => {
      finished = true;
      return result;
    });

    await vi.advanceTimersByTimeAsync(1500);
    expect(finished).toBe(false);
    await vi.advanceTimersByTimeAsync(1500);
    expect(finished).toBe(false);
    await vi.advanceTimersByTimeAsync(1500);
    await expect(pending).resolves.toMatchObject({ state: 'succeeded', updated_at: 'T1' });
  });

  it('fails with the reason the service recorded', async () => {
    vi.useFakeTimers();
    const answers = [
      run({ updated_at: 'T0' }),
      run({ state: 'failed', updated_at: 'T1', error: 'DXF не записался: диск полон.' }),
    ];
    mockApi({
      '/api/v1/runs/r1': () => Response.json(answers.shift()),
      'POST /api/v1/runs/r1/rebuild': summary,
    });
    const pending = new PlanEditor('r1').rebuild();
    const outcome = expect(pending).rejects.toThrow('DXF не записался: диск полон.');
    await vi.advanceTimersByTimeAsync(1500);
    await outcome;
  });
});
