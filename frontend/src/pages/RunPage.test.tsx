import { act, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import type { BasemapJson, PlanJson, QualityJson, RulesJson } from '../api/artifacts';
import type { ArtifactOut, RunOut } from '../api/types';
import { toMapItems } from '../map/items';
import { useWorkspace } from '../state/workspace';
import { mockApi, run } from '../test/api';
import { renderApp } from '../test/render';

// Холст и движок в jsdom не рисуют: их проверяют модульные тесты движка и живой браузер.
// Здесь - всё вокруг карты: панели, сводка, объяснения, выгрузка.
vi.mock('../components/run/PlanMap', () => ({
  PlanMap: () => <canvas aria-label="План посадок" />,
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
    expect(await within(left).findByText(/требуется проверка/)).toBeVisible();
    expect(left).not.toHaveTextContent('все без ограничений');
    expect(left).toHaveTextContent(
      'Грунт под всей посадочной ямой не подтверждён замкнутыми контурами у 40 из 40 посадок',
    );
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
    expect(left).toHaveTextContent('посадки в плане, все без ограничений');
    expect(left).toHaveTextContent('161 место отклонено. Подоснова цела');
    // Индекс качества - один раз, крупно справа; в пульте слева он был дублем.
    const right = await screen.findByRole('complementary', { name: 'Состав плана' });
    expect(await within(right).findByText('0,81')).toBeInTheDocument();
    expect(within(left).queryByText('0,81')).toBeNull();
    expect(document.body).toHaveClass('shell-map');
  });

  it('shows what the plan is made of until a placement is picked', async () => {
    mockApi(succeededRoutes());
    renderApp('/runs/r1');

    const right = await screen.findByRole('complementary', { name: 'Состав плана' });
    expect(await within(right).findByRole('heading', { name: 'Состав плана: 3' })).toBeVisible();
    expect(within(right).getByRole('button', { name: /Липа мелколистная/ })).toHaveTextContent('2');
    expect(within(right).getByRole('heading', { name: 'Качество плана' })).toBeVisible();
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
    expect(within(right).getByRole('heading', { name: 'Почему этот вид' })).toBeVisible();
    expect(right).toHaveTextContent('Пригодность месту 74%');

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

    await userEvent.click(within(right).getByRole('button', { name: 'к составу плана' }));
    expect(useWorkspace.getState().selected).toBeNull();
  });

  it('offers the DXF and the interpretations first, with their sizes', async () => {
    mockApi(succeededRoutes());
    renderApp('/runs/r1');

    const dxf = await screen.findByRole('link', { name: /Скачать DXF/ });
    expect(dxf).toHaveAttribute('href', '/api/v1/runs/r1/artifacts/result.dxf');
    expect(dxf).toHaveTextContent('1,5 МБ');
    expect(screen.getByRole('link', { name: /Интерпретации, CSV/ })).toHaveTextContent('30 КБ');
    expect(screen.getByText('Файлы прогона: 4')).toBeInTheDocument();
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
    expect(within(left).getByText('Как собран план: 2')).toBeInTheDocument();
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
    // Заглушка matchMedia в тестах - не высокий экран: обозначения закрыты и не отнимают
    // у пульта треть высоты.
    mockApi(succeededRoutes());
    renderApp('/runs/r1');

    const toggle = await screen.findByRole('button', { name: 'обозначения' });
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

    await userEvent.click(await screen.findByRole('button', { name: 'обозначения' }));
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
