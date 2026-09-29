import { act, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import type { BasemapJson, PlanJson, QualityJson, RulesJson } from '../api/artifacts';
import type { ArtifactOut, PlanSummaryOut, RunOut } from '../api/types';
import { toMapItems } from '../map/items';
import type { EngineHooks } from '../map/types';
import { useWorkspace } from '../state/workspace';
import { mockApi, run } from '../test/api';
import { renderApp } from '../test/render';

// Холст и движок в jsdom не рисуют: их проверяют модульные тесты движка и живой браузер.
// Здесь - всё вокруг карты: панели, сводка, объяснения, выгрузка. Обработчики карты
// (удаление, перенос) тест вызывает сам, как их вызвал бы движок.
const map = vi.hoisted(() => ({ hooks: null as { current: EngineHooks } | null }));
vi.mock('../components/run/PlanMap', () => ({
  PlanMap: ({ hooks }: { hooks: { current: EngineHooks } }) => {
    map.hooks = hooks;
    return <canvas aria-label="План посадок" />;
  },
}));

const artifact = (name: string, size: number | null = 2048): ArtifactOut => ({
  name,
  url: `/api/v1/runs/r1/artifacts/${name}`,
  size_bytes: size,
});

const linden = {
  code: 'tilia_cordata',
  name_ru: 'Липа мелколистная',
  name_lat: 'Tilia cordata',
  crown_diameter_m: 6,
  life_form: 'tree',
};
const maple = { ...linden, code: 'acer_platanoides', name_ru: 'Клён остролистный' };

const plan: PlanJson = {
  run_id: 'r1',
  source: { name: 'Тестовая улица.dxf', sha256: 'x', dxf_version: 'AC1032' },
  summary: {},
  placements: [1, 2, 3].map((number) => ({
    id: `p${String(number)}`,
    number,
    planting_type: 'tree',
    species: number === 3 ? maple : linden,
    x: 100 + number * 6,
    y: 50,
    verdict: 'allowed',
    notes: [],
    explanation: `Посадка №${String(number)} допускается.`,
    assortment:
      number === 1
        ? {
            status: 'assigned',
            percent: 74,
            factors: {},
            structure: { id: null, kind: null },
            reasons: [
              {
                kind: 'norm',
                text: 'рекомендован для категории «улицы и дороги»',
                rule_id: 'R-MGSN-CATEGORY-001',
                source: null,
                condition: null,
              },
            ],
            alternatives: [],
          }
        : null,
    value: null,
    checks: [
      {
        rule_id: 'R-UTIL-WATER-001',
        outcome: 'pass',
        measured_m: 2.4,
        threshold_m: 2,
        object_class: 'water',
      },
    ],
  })),
  rejections: [],
  warnings: [],
};

const rules: RulesJson = {
  fingerprint: 'abc',
  total: 1,
  rules: {
    'R-UTIL-WATER-001': {
      rule_id: 'R-UTIL-WATER-001',
      object_class: 'water',
      min_distance_m: 2,
      measure_to: 'trunk_axis',
      severity: 'hard',
      act_id: 'sp42',
      act_title: 'СП 42.13330.2016',
      act_short: 'СП 42.13330.2016',
      act_edition: '2016',
      url: '',
      clause: 'табл. 9.1',
      quote: 'Водопровод - 2,0 м.',
      status: 'verified',
      related: [],
    },
  },
};

const quality: QualityJson = {
  index: 0.81,
  gate: 'ok',
  summary: ['Индекс 0,81.'],
  terms: [
    {
      key: 'canopy',
      title: 'Площадь крон',
      weight: 0.2,
      score: 0.9,
      basis: 'МГСН В.1',
      note: 'Кроны закрывают 40% тротуара.',
      measure: {},
    },
  ],
};

const basemap: BasemapJson = {
  type: 'FeatureCollection',
  bbox: [0, 0, 200, 100],
  features: [],
};

const done = (overrides: Partial<RunOut> = {}) =>
  run({
    artifacts: [
      artifact('result.dxf', 1_572_864),
      artifact('interpretations.csv', 30_720),
      artifact('plan.json'),
      artifact('rules.json'),
      artifact('quality.json'),
      artifact('basemap.geojson'),
    ],
    ...overrides,
  });

/** Раскрыть <details> по тексту его summary, как это сделал бы человек. */
async function openFold(scope: HTMLElement, summary: string | RegExp) {
  const toggle = within(scope).getByText(summary, { selector: 'summary' });
  await userEvent.click(toggle);
  expect(toggle.closest('details')).toHaveAttribute('open');
}

/** Значение строки «подпись - число» в списке определений по её подписи. */
const fact = (scope: HTMLElement, term: string) =>
  within(scope).getByText(term, { selector: 'dt' }).nextElementSibling;

function succeededRoutes(record: RunOut = done()) {
  return {
    '/api/v1/runs/r1': record,
    '/api/v1/runs/r1/artifacts/plan.json': plan,
    '/api/v1/runs/r1/artifacts/rules.json': rules,
    '/api/v1/runs/r1/artifacts/quality.json': quality,
    '/api/v1/runs/r1/artifacts/basemap.geojson': basemap,
  };
}

describe('RunPage: finished run', () => {
  it('does not call inferred ground unrestricted and shows pits requiring review', async () => {
    const record = done();
    mockApi(
      succeededRoutes({
        ...record,
        summary: {
          ...record.summary,
          placements: 40,
          surface_inference_review_required: true,
          surface_unconfirmed_placements: 40,
        },
      }),
    );
    renderApp('/runs/r1');
    const left = await screen.findByRole('complementary', { name: 'Прогон' });
    // План на предположении о грунте - эскиз, и это сказано у числа, а не в журнале.
    const title = await within(left).findByText('Эскиз · проверить');
    expect(title).toBeVisible();
    const notice = title.closest('.notice');
    expect(notice).toHaveTextContent('Грунт под ямой не подтверждён40 из 40');
    expect(left).not.toHaveTextContent('все без ограничений');
    // Почему эскиз и что делать - под раскрытием в том же блоке.
    await openFold(left, 'Почему эскиз и что сделать');
    expect(within(left).getByText(/Допустимость посадок не подтверждена/)).toBeVisible();
    expect(
      within(left).getByText(/грунт под всей посадочной ямой должен быть подтверждён/i),
    ).toBeVisible();
  });

  it('leads with the number of placements and the integrity of the base drawing', async () => {
    mockApi(succeededRoutes());
    renderApp('/runs/r1');

    const left = await screen.findByRole('complementary', { name: 'Прогон' });
    // Имя чертежа без расширения: «.dxf» у каждого прогона ничего не различает.
    expect(await within(left).findByRole('heading', { level: 1 })).toHaveTextContent(
      /^Тестовая улица$/,
    );
    expect(await within(left).findByText('302')).toBeInTheDocument();
    expect(left.querySelector('.metric')).toHaveTextContent(/^302посадки в плане$/);
    // Целая подоснова - не тревога: нарушение сказано у числа, иначе строка в деталях.
    expect(left.querySelector('.metric-bad')).toBeNull();
    await openFold(left, 'Детали расчёта');
    expect(fact(left, 'Отклонено мест')).toHaveTextContent(/^161$/);
    expect(fact(left, 'Подоснова')).toHaveTextContent(/^Без изменений$/);
    // Индекс качества - один раз, крупно справа; в пульте слева он был дублем.
    const right = await screen.findByRole('complementary', { name: 'Состав плана' });
    await userEvent.click(within(right).getByRole('button', { name: 'Эффект' }));
    expect(await within(right).findByText('0,81')).toBeVisible();
    expect(within(left).queryByText('0,81')).toBeNull();
    expect(document.body).toHaveClass('shell-map');
  });

  // Ответ сервиса на правку: число посадок черновика и посадки, которые правка перевела в отказ.
  const edited = (
    placements: number,
    rejected: PlanSummaryOut['rejected_by_edit'] = [],
  ): PlanSummaryOut => ({
    placements,
    allowed: placements,
    needs_approval: 0,
    rejections: rejected.length,
    stale: true,
    rejected_by_edit: rejected,
  });
  const three = done({
    summary: { placements: 3, needs_approval: 0, rejections: 0, integrity_ok: true },
  });
  const metric = () => {
    const left = screen.getByRole('complementary', { name: 'Прогон' });
    const node = left.querySelector<HTMLElement>('.metric');
    if (!node) throw new Error('нет числа посадок в панели прогона');
    return node;
  };

  it('counts the edit draft on the left, as the plan composition does, until the DXF is rebuilt', async () => {
    // Жюри (этап 21, R-20): после удаления посадки слева «1278 посадок в плане», справа
    // «Состав плана: 1277».
    let rebuilt = false;
    const after = {
      ...three,
      updated_at: '2026-09-23T09:20:00Z',
      summary: { ...three.summary, placements: 2 },
    };
    const trimmed: PlanJson = { ...plan, placements: plan.placements.slice(1) };
    mockApi({
      ...succeededRoutes(three),
      '/api/v1/runs/r1': () => Response.json(rebuilt ? after : three),
      '/api/v1/runs/r1/artifacts/plan.json': () => Response.json(rebuilt ? trimmed : plan),
      'POST /api/v1/runs/r1/edits': edited(2),
      'POST /api/v1/runs/r1/rebuild': () => {
        rebuilt = true;
        return Response.json({ ...edited(2), stale: false });
      },
    });
    renderApp('/runs/r1');
    const left = await screen.findByRole('complementary', { name: 'Прогон' });
    const right = await screen.findByRole('complementary', { name: 'Состав плана' });
    await within(right).findByRole('heading', { name: 'Состав плана: 3' });
    expect(metric()).toHaveTextContent(/^3посадки в плане$/);

    const target = toMapItems(plan).placements[0];
    if (!target) throw new Error('нет посадки в плане');
    act(() => {
      map.hooks?.current.remove(target);
    });

    await within(right).findByRole('heading', { name: 'Состав плана: 2' });
    // Слева то же число, что справа, и видно, что это черновик правок, а не итог прогона.
    await waitFor(() => {
      expect(metric()).toHaveTextContent(/^2посадки в плане · черновик правок$/);
    });
    // Разбивка сходится с числом черновика и не пропадает.
    const breakdown = left.querySelector('.run-breakdown');
    expect(breakdown).toHaveTextContent('Деревья2');
    expect(breakdown).toHaveTextContent('Кустарники0');

    // После пересборки число - итог прогона, метки черновика нет.
    await userEvent.click(within(left).getByRole('button', { name: 'Пересобрать DXF' }));
    await waitFor(
      () => {
        expect(metric()).toHaveTextContent(/^2посадки в плане$/);
      },
      { timeout: 6000 },
    );
    expect(within(right).getByRole('heading', { name: 'Состав плана: 2' })).toBeVisible();
    expect(left.querySelector('.run-breakdown')).toHaveTextContent('Деревья2');
  }, 10_000);

  it('leaves out of both counts a placement the edit moved into a rejection', async () => {
    mockApi({
      ...succeededRoutes(three),
      'POST /api/v1/runs/r1/edits': edited(2, [
        { placement_id: 'p2', reason: 'Ближе 2,0 м к водопроводу.' },
      ]),
      'POST /api/v1/runs/r1/check': {
        verdict: 'forbidden',
        plantable: true,
        needs_barrier: false,
        note: '',
        checks: [],
      },
    });
    renderApp('/runs/r1');
    const left = await screen.findByRole('complementary', { name: 'Прогон' });
    const right = await screen.findByRole('complementary', { name: 'Состав плана' });
    await within(right).findByRole('heading', { name: 'Состав плана: 3' });

    const target = toMapItems(plan).placements[1];
    if (!target) throw new Error('нет посадки в плане');
    act(() => {
      map.hooks?.current.move(target, 130, 50, { x: target.x, y: target.y });
    });

    // Сервис держит перенесённую посадку в отказах черновика: её нет ни слева, ни справа.
    await within(right).findByRole('heading', { name: 'Состав плана: 2' });
    await waitFor(() => {
      expect(metric()).toHaveTextContent(/^2посадки в плане · черновик правок$/);
    });
    expect(left.querySelector('.run-breakdown')).toHaveTextContent('Деревья2');
  });

  it('shows what the plan is made of until a placement is picked', async () => {
    mockApi(succeededRoutes());
    renderApp('/runs/r1');

    const right = await screen.findByRole('complementary', { name: 'Состав плана' });
    expect(await within(right).findByRole('heading', { name: 'Состав плана: 3' })).toBeVisible();
    expect(within(right).getByRole('button', { name: /Липа мелколистная/ })).toHaveTextContent('2');
    // Оценка плана - соседний раздел той же панели, в один клик.
    const effect = within(right).getByRole('button', { name: 'Эффект' });
    expect(effect).toHaveAttribute('aria-pressed', 'false');
    await userEvent.click(effect);
    expect(effect).toHaveAttribute('aria-pressed', 'true');
    expect(within(right).getByRole('heading', { name: 'Оценка плана' })).toBeVisible();
  });

  it('explains a picked placement by the rule, the act and its clause', async () => {
    mockApi(succeededRoutes());
    renderApp('/runs/r1');
    const right = await screen.findByRole('complementary', { name: 'Состав плана' });
    await within(right).findByRole('heading', { name: 'Состав плана: 3' });

    // Живая область стоит в разметке заранее: читалка объявляет только изменения в ней.
    const announce = document.getElementById('selection-announce');
    expect(announce).toHaveTextContent('');
    expect(announce).toHaveAttribute('role', 'status');

    const picked = toMapItems(plan).placements[0] ?? null;
    act(() => {
      useWorkspace.getState().select(picked);
    });

    expect(announce).toHaveTextContent('Выбрана посадка № 1. Липа мелколистная, допускается');

    expect(within(right).getByRole('heading', { name: '№ 1. Липа мелколистная' })).toBeVisible();
    expect(within(right).getByText('допускается')).toBeVisible();
    expect(within(right).getByText('Ближе всего к норме')).toBeVisible();
    expect(right).toHaveTextContent(
      'R-UTIL-WATER-001 · норма 2,00 м · СП 42.13330.2016, табл. 9.1',
    );
    // Норма - первой, выбор растения - под раскрытием.
    expect(within(right).getByRole('heading', { name: 'Почему этот вид' })).not.toBeVisible();
    await openFold(right, 'О растении и его выборе');
    expect(within(right).getByRole('heading', { name: 'Почему этот вид' })).toBeVisible();
    expect(right).toHaveTextContent('Пригодность места 74%');

    // Перенос без перетаскивания: кнопка есть только в режиме правки.
    expect(within(right).queryByRole('button', { name: /новое место/ })).toBeNull();
    act(() => {
      useWorkspace.getState().setEditing(true);
    });
    const place = within(right).getByRole('button', { name: 'Указать новое место на карте' });
    expect(place).toHaveAttribute('aria-pressed', 'false');
    act(() => {
      useWorkspace.getState().setPlacing(true);
    });
    expect(place).toHaveAttribute('aria-pressed', 'true');
    expect(
      within(right).getByText(/Кликните точку на карте: посадка № 1 переедет туда/),
    ).toBeVisible();

    await userEvent.click(within(right).getByRole('button', { name: '← К плану' }));
    expect(useWorkspace.getState().selected).toBeNull();
  });

  it('offers the DXF first and the interpretations one click away, with their sizes', async () => {
    mockApi(succeededRoutes());
    renderApp('/runs/r1');

    const right = await screen.findByRole('complementary', { name: 'Состав плана' });
    const dxf = await within(right).findByRole('link', { name: /Скачать план DXF/ });
    expect(dxf).toBeVisible();
    expect(dxf).toHaveAttribute('href', '/api/v1/runs/r1/artifacts/result.dxf');
    expect(dxf).toHaveAttribute('download');
    expect(dxf).toHaveTextContent('1,5 МБ');

    await openFold(right, 'Отчёты и другие файлы');
    const csv = within(right).getByRole('link', { name: /Нормы · CSV/ });
    expect(csv).toBeVisible();
    expect(csv).toHaveAttribute('href', '/api/v1/runs/r1/artifacts/interpretations.csv');
    expect(csv).toHaveTextContent('30 КБ');
    // Служебные файлы - ещё глубже, числом: plan, rules, quality, basemap.
    expect(within(right).getByText('Файлы расчёта · 4', { selector: 'summary' })).toBeVisible();
  });

  it('puts warnings that change the meaning of the plan next to the number', async () => {
    const warnings = [
      'Граница работ не найдена: участок ограничен габаритами чертежа.',
      'Слой 0 пуст.',
    ];
    mockApi(
      succeededRoutes(
        done({
          summary: {
            placements: 302,
            needs_approval: 0,
            rejections: 161,
            integrity_ok: true,
            warnings,
          },
        }),
      ),
    );
    renderApp('/runs/r1');

    const left = await screen.findByRole('complementary', { name: 'Прогон' });
    // Ключевое предупреждение стоит у числа и остаётся в полном списке под раскрытием.
    const copies = await within(left).findAllByText(warnings[0] ?? '');
    expect(copies.map((node) => Boolean(node.closest('.notice')))).toEqual([true, false]);
    expect(copies[0]).toBeVisible();
    expect(copies[1]).not.toBeVisible();
    await openFold(left, 'Детали расчёта');
    await openFold(left, 'Как собран план · 2');
    expect(copies[1]).toBeVisible();
    expect(within(left).getByText('Слой 0 пуст.')).toBeVisible();
  });

  it('remembers a collapsed panel', async () => {
    mockApi(succeededRoutes());
    renderApp('/runs/r1');

    const toggle = await screen.findByRole('button', { name: 'Свернуть панель прогона' });
    await userEvent.click(toggle);

    expect(screen.getByRole('complementary', { name: 'Прогон' })).toHaveClass('collapsed');
    expect(screen.getByRole('button', { name: 'Развернуть панель прогона' })).toHaveAttribute(
      'aria-expanded',
      'false',
    );
    expect(localStorage.getItem('green-panel-left')).toBe('1');
  });

  it('keeps the legend one click away on an ordinary screen and remembers the choice', async () => {
    // Обозначения по умолчанию закрыты: виды плана со знаками уже есть в составе справа.
    mockApi(succeededRoutes());
    renderApp('/runs/r1');

    const toggle = await screen.findByRole('button', { name: 'легенда' });
    expect(toggle).toHaveAttribute('aria-pressed', 'false');
    expect(screen.queryByRole('complementary', { name: 'Условные обозначения' })).toBeNull();

    await userEvent.click(toggle);
    const legend = screen.getByRole('complementary', { name: 'Условные обозначения' });
    expect(legend).toBeVisible();
    expect(localStorage.getItem('green-legend')).toBe('1');

    await userEvent.click(screen.getByRole('button', { name: 'Скрыть условные обозначения' }));
    expect(legend).not.toBeVisible();
    expect(toggle).toHaveAttribute('aria-pressed', 'false');
  });

  it('keeps weak places off the overview until they are asked for', async () => {
    // Чёрные треугольники были самым контрастным знаком обзора (жюри, итерация 7): по
    // умолчанию их нет, галочка в обозначениях включает.
    mockApi(succeededRoutes());
    renderApp('/runs/r1');

    await userEvent.click(await screen.findByRole('button', { name: 'легенда' }));
    const legend = screen.getByRole('complementary', { name: 'Условные обозначения' });
    const weak = within(legend).getByRole('checkbox', { name: /Слабые места/ });
    expect(weak).not.toBeChecked();
    expect(within(legend).getByRole('checkbox', { name: 'Посадки плана' })).toBeChecked();
    await userEvent.click(weak);
    expect(useWorkspace.getState().layers.weak).toBe(true);
  });
});

describe('RunPage: run in progress', () => {
  it('shows the stage, the share done and the time left', async () => {
    mockApi({
      '/api/v1/runs/r1': run({
        state: 'running',
        summary: undefined,
        progress: {
          stage: 'placement',
          title: 'Расставляем посадки',
          fraction: 0.42,
          elapsed_s: 30,
          eta_s: 50,
          steps: [
            { id: 'read', title: 'Читаем чертёж', state: 'done' },
            { id: 'placement', title: 'Расставляем посадки', state: 'active' },
            { id: 'write', title: 'Пишем DXF', state: 'pending' },
          ],
        },
      }),
    });
    renderApp('/runs/r1');

    const hud = await screen.findByRole('region', { name: 'Ход расчёта' });
    expect(within(hud).getByText('Расставляем посадки')).toBeVisible();
    expect(within(hud).getByRole('progressbar')).toHaveAttribute('aria-valuenow', '42');
    expect(hud).toHaveTextContent('этап 2 из 3');
    expect(hud).toHaveTextContent('осталось');
    // Пока план не готов, панели состава и выгрузки нет.
    expect(screen.queryByRole('complementary', { name: 'Состав плана' })).toBeNull();
  });

  it('keeps the queue position honest', async () => {
    mockApi({ '/api/v1/runs/r1': run({ state: 'queued', summary: undefined }) });
    renderApp('/runs/r1');

    const hud = await screen.findByRole('region', { name: 'Ход расчёта' });
    expect(within(hud).getByText('В очереди')).toBeVisible();
    expect(hud).toHaveTextContent('ждём свободного места');
  });
});

describe('RunPage: failures', () => {
  it('says why the run failed and leads back to the console', async () => {
    mockApi({
      '/api/v1/runs/r1': run({
        state: 'failed',
        summary: undefined,
        error: 'Чертёж не читается: файл обрезан.',
      }),
    });
    renderApp('/runs/r1');

    expect(await screen.findByRole('heading', { name: 'Прогон не удался' })).toBeVisible();
    expect(screen.getByText('Чертёж не читается: файл обрезан.')).toBeVisible();
    // Одно имя у ссылки на консоль по всему интерфейсу (жюри, итерация 9): в шапке панели и
    // в карточке неудавшегося прогона она одна и та же.
    const back = screen.getAllByRole('link', { name: '← все прогоны' });
    expect(back.length).toBeGreaterThan(0);
    for (const link of back) expect(link).toHaveAttribute('href', '/');
    // Причина и есть весь текст сервиса: раскрывать нечего.
    expect(screen.queryByText('Подробности')).toBeNull();
  });

  it('turns a raw reading failure into a reason and an action, the raw text under details', async () => {
    const raw =
      'Неполная геометрия входного чертежа: XREF XREF_ИГДИ_Олимпийская; XREF XREF_Сети; ' +
      "REGION, слой 'Газ', блок None: 3 (missing-acis-data), примеры h:1A, h:2B. Расчёт " +
      'остановлен: загрузите внешние ссылки. Наличие других сетей не заменяет потерянные данные.';
    mockApi({
      '/api/v1/runs/r1': run({ state: 'failed', summary: undefined, error: raw }),
    });
    renderApp('/runs/r1');

    const card = (await screen.findByRole('heading', { name: 'Прогон не удался' })).closest(
      '.status',
    );
    expect(card).toHaveAttribute('data-state', 'failed');
    expect(card).toHaveTextContent(
      'Чертёж прочитан не полностью: не найдены 2 внешние ссылки, у части объектов нет геометрии.',
    );
    expect(card).toHaveTextContent(
      'Пересохраните DXF вместе с внешними ссылками и запустите снова.',
    );
    // Сырой текст остаётся, но под раскрытием, а не строкой в двести знаков.
    const details = screen.getByText('Подробности').closest('details');
    expect(details).not.toHaveAttribute('open');
    expect(details).toHaveTextContent('missing-acis-data');
    // Скелетон «посадок в плане» у неудачи не разрешился бы никогда: его нет.
    const left = screen.getByRole('complementary', { name: 'Прогон' });
    expect(left).not.toHaveTextContent('посадок в плане');
    expect(left.querySelector('.skeleton')).toBeNull();
  });

  it('names a run that is not in the store', async () => {
    mockApi({});
    renderApp('/runs/nope');

    expect(await screen.findByRole('heading', { name: 'Такого прогона нет' })).toBeVisible();
    expect(screen.getByText('Прогона nope нет в хранилище сервиса.')).toBeVisible();
  });
});
