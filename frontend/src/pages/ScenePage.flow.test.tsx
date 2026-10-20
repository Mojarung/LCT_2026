import { QueryClientProvider } from '@tanstack/react-query';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';

import { makeQueryClient } from '../api/queryClient';
import type { PhotoOut } from '../api/types';
import type { AutoShot } from '../scene3d/autoshots';
import type * as EngineModule from '../scene3d/engine';
import type { EngineEvents, Hover } from '../scene3d/engine';
import type { Building, Plant, World } from '../scene3d/types';
import { type Call, mockApi, run } from '../test/api';
import { ScenePage } from './ScenePage';

/* 3D-вид с подменённым движком: jsdom не даёт WebGL, а страница - это пульт вокруг движка.
 * Фейк запоминает вызовы и отдаёт странице события движка (ход сборки, наведение, камера),
 * тест проверяет, что видит и что может сделать пользователь. Сам движок тестируется отдельно. */

const h = vi.hoisted(() => {
  class FakeEngine {
    softwareRendering = false;
    touring = false;
    freecam = {
      mode: 'fly' as 'fly' | 'walk',
      pose: { x: 0, y: 30, z: 0, yaw: 0, pitch: -0.5 },
    };
    readonly apply = vi.fn();
    readonly setTreeClearanceConflicts = vi.fn();
    readonly teleportTo = vi.fn(() => true);
    readonly setView = vi.fn();
    readonly addContext = vi.fn(() => 12);
    readonly dispose = vi.fn();
    readonly setPaused = vi.fn();
    readonly capture = vi.fn(() => Promise.resolve(new Blob(['png'], { type: 'image/png' })));
    readonly speciesHere = vi.fn(() => ({
      viewpoint: 'aerial' as const,
      trees: ['Tilia cordata'],
      shrubs: [] as string[],
      buildings: true,
    }));
    readonly planShots = vi.fn((): AutoShot[] => [
      {
        key: 'street-0',
        pose: { x: 1, y: 30, z: 2, yaw: 0, pitch: -0.5 },
        viewpoint: 'aerial',
        label: 'Сверху',
        trees: ['Tilia cordata'],
        shrubs: [],
        names: ['Липа мелколистная'],
        mark: { u: 0.5, v: 0.5 },
        buildings: true,
      },
    ]);
    readonly renderViews = vi.fn((poses: unknown[]) =>
      Promise.resolve(poses.map(() => new Blob(['view'], { type: 'image/png' }))),
    );
    readonly viewShot = vi.fn(() =>
      Promise.resolve({
        blob: new Blob(['view'], { type: 'image/png' }),
        viewpoint: 'ground' as const,
        trees: ['Tilia cordata'],
        shrubs: ['Spiraea japonica'],
        buildings: false,
      }),
    );
    readonly setMode = vi.fn();
    readonly resetView = vi.fn();
    readonly startTour = vi.fn();
    readonly stopTour = vi.fn();
    readonly setSpeed = vi.fn();
    constructor(readonly events: EngineEvents) {}
  }
  const state = {
    webgl: true,
    /** Не сообщать «готово»: тест сам ведёт ход сборки. */
    hold: false,
    software: false,
    failure: null as string | null,
    engine: null as FakeEngine | null,
    world: null as World | null,
  };
  const create = vi.fn(
    (_canvas: HTMLCanvasElement, _world: World, _image: unknown, events: EngineEvents) => {
      if (state.failure) return Promise.reject(new Error(state.failure));
      const engine = new FakeEngine(events);
      engine.softwareRendering = state.software;
      state.engine = engine;
      events.progress?.('plants', 3, 10);
      if (!state.hold) events.progress?.('ready', 1, 1);
      return Promise.resolve(engine);
    },
  );
  return { state, create };
});

vi.mock('../scene3d/engine', async (importOriginal) => {
  const real = await importOriginal<typeof EngineModule>();
  return {
    ...real,
    webglAvailable: () => h.state.webgl,
    SceneEngine: { create: h.create },
  };
});

vi.mock('../scene3d/world', () => ({
  buildWorld: () => h.state.world,
}));

const species = {
  name_ru: 'Липа мелколистная',
  name_lat: 'Tilia cordata',
  life_form: 'tree',
  height_m: 4,
  crown_diameter_m: 3,
  crown_mature_m: 8,
  evergreen: false,
  conifer: false,
  growth: 'medium',
  genus: 'Tilia',
  family: 'Malvaceae',
};

function plant(patch: Partial<Plant> = {}): Plant {
  return {
    id: 'p1',
    number: 1,
    x: 0,
    z: 0,
    type: 'tree',
    code: 'tilia_cordata',
    name: 'Липа мелколистная',
    species,
    existing: false,
    seed: 1,
    ...patch,
  };
}

function building(kind: Building['kind']): Building {
  return { rings: [], height: 9, floors: 3, source: 'label', kind, wall: null, use: null, seed: 1 };
}

function world(patch: Partial<World> = {}): World {
  return {
    origin: [0, 0],
    bounds: [0, 0, 100, 100],
    buildings: [building('building'), building('building'), building('porch')],
    plants: [
      plant(),
      plant({ id: 'p2', number: 2 }),
      plant({ id: 's1', number: 3, type: 'shrub', name: 'Спирея японская' }),
      plant({ id: 'e1', number: undefined, type: 'existing_tree', existing: true }),
      plant({ id: 'e2', number: undefined, type: 'existing_tree', existing: true, strip: true }),
    ],
    curbs: [],
    fences: [],
    poles: [],
    lawns: [],
    sidewalks: [],
    roads: [],
    floorsBy: { label: 2, neighbor: 0, letter: 1, assumed: 0 },
    fallback: false,
    ...patch,
  };
}

function photo(patch: Partial<PhotoOut> = {}): PhotoOut {
  return {
    id: 'ph1',
    state: 'succeeded',
    scenery: false,
    season: 'summer',
    hour: 11,
    viewpoint: 'aerial',
    species: [],
    shrubs: [],
    shot: 'Кадры улицы. Сверху',
    modern: true,
    custom: false,
    width: 1536,
    height: 864,
    created_at: '2026-10-20T10:00:00Z',
    started_at: '2026-10-20T10:00:05Z',
    finished_at: '2026-10-20T10:01:30Z',
    seconds: 84.6,
    error: null,
    upscaled: false,
    source_url: '/frame.png',
    photo_url: '/photo.jpg',
    raw_url: '/raw.jpg',
    ...patch,
  };
}

const RUN = '/api/v1/runs/r1';
const PHOTOS = '/api/v1/runs/r1/photos';

function routes(extra: Record<string, unknown> = {}) {
  return {
    [RUN]: run(),
    [PHOTOS]: { available: true, reason: null, photos: [] },
    [`POST ${PHOTOS}`]: photo({ id: 'new', state: 'queued' }),
    ...extra,
  };
}

function renderScene(path = '/runs/r1/3d') {
  const router = createMemoryRouter(
    [
      { path: '/runs/:runId/3d', element: <ScenePage /> },
      { path: '/runs/:runId', element: <p>План прогона</p> },
    ],
    { initialEntries: [path] },
  );
  const client = makeQueryClient();
  client.setDefaultOptions({ queries: { retry: false, refetchOnWindowFocus: false } });
  render(
    <QueryClientProvider client={client}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return { router };
}

function engine() {
  const e = h.state.engine;
  if (!e) throw new Error('движок не создан');
  return e;
}

async function ready() {
  await screen.findByRole('toolbar', { name: 'Камера и снимки' });
  return engine();
}

const formOf = (call: Call | undefined) => call?.init?.body as FormData;
const posts = (calls: Call[]) => calls.filter((c) => c.method === 'POST' && c.url === PHOTOS);

const createUrl = vi.fn((blob: Blob) => `blob:${String(blob.size)}-${String(Math.random())}`);
const revokeUrl = vi.fn();

beforeAll(() => {
  HTMLDialogElement.prototype.showModal = function () {
    this.setAttribute('open', '');
  };
  HTMLDialogElement.prototype.close = function () {
    this.removeAttribute('open');
  };
  URL.createObjectURL = createUrl;
  URL.revokeObjectURL = revokeUrl;
});

beforeEach(() => {
  h.state.webgl = true;
  h.state.hold = false;
  h.state.software = false;
  h.state.failure = null;
  h.state.engine = null;
  h.state.world = world();
  h.create.mockClear();
  createUrl.mockClear();
  revokeUrl.mockClear();
  vi.stubGlobal(
    'createImageBitmap',
    vi.fn(() => Promise.resolve({ width: 1920, height: 1080, close: vi.fn() })),
  );
});

afterEach(() => {
  vi.restoreAllMocks();
  window.history.replaceState(null, '', '/');
});

describe('3D-вид: экран сборки', () => {
  it('пока прогон считается, говорит, что 3D откроется после плана', async () => {
    mockApi(routes({ [RUN]: run({ state: 'running' }) }));
    renderScene();
    expect(await screen.findByText(/Прогон ещё считается/)).toBeInTheDocument();
    expect(h.create).not.toHaveBeenCalled();
  });

  it('прогон с ошибкой и пропавший прогон - причина, а не вечная загрузка', async () => {
    mockApi(routes({ [RUN]: run({ state: 'failed' }) }));
    renderScene();
    expect(await screen.findByText('Прогон завершился ошибкой: строить нечего.')).toBeVisible();
  });

  it('не найденный прогон', async () => {
    mockApi({});
    renderScene();
    expect(await screen.findByText('Прогон не найден.')).toBeVisible();
    expect(screen.getByRole('link', { name: '← к плану прогона' })).toHaveAttribute(
      'href',
      '/runs/r1',
    );
  });

  it('не загрузился scene.json - сцену не построить', async () => {
    mockApi(routes({ [RUN]: run({ artifacts: [{ name: 'scene.json' }] as never }) }));
    renderScene();
    expect(await screen.findByText('Не загрузился scene.json, сцену не построить.')).toBeVisible();
  });

  it('сбой движка показывается текстом', async () => {
    h.state.failure = 'контекст WebGL потерян';
    mockApi(routes());
    renderScene();
    expect(
      await screen.findByText('3D-вид не собрался: контекст WebGL потерян'),
    ).toBeInTheDocument();
  });

  it('этапы сборки: число крон и отметки пройденных этапов', async () => {
    h.state.hold = true;
    mockApi(routes());
    renderScene();
    expect(await screen.findByText(/Кроны деревьев и кустарников · 3 из 10/)).toBeVisible();
    const steps = screen.getAllByRole('listitem');
    expect(steps.map((li) => li.dataset.state)).toEqual(['done', 'done', 'done', 'active']);
    act(() => {
      engine().events.progress?.('buildings', 0, 1);
    });
    expect(screen.getAllByRole('listitem').map((li) => li.dataset.state)).toEqual([
      'done',
      'done',
      'active',
      'wait',
    ]);
    act(() => {
      engine().events.progress?.('ready', 1, 1);
    });
    expect(await screen.findByRole('toolbar', { name: 'Камера и снимки' })).toBeVisible();
    expect(screen.getByText(/3D-вид готов, 11:00/)).toBeInTheDocument();
  });

  it('собирает сцену из scene.json, подосновы и карты покрытий', async () => {
    const calls = mockApi(
      routes({
        [RUN]: run({
          artifacts: [
            { name: 'scene.json' },
            { name: 'basemap.geojson' },
            { name: 'surface.json' },
          ] as never,
        }),
        '/api/v1/runs/r1/artifacts/scene.json': { version: 2 },
        '/api/v1/runs/r1/artifacts/basemap.geojson': { type: 'FeatureCollection', features: [] },
        '/api/v1/runs/r1/artifacts/surface.json': {
          origin: [0, 0],
          cell_m: 0.5,
          width: 10,
          height: 10,
        },
      }),
    );
    renderScene();
    await ready();
    const urls = calls.map((c) => c.url);
    expect(urls).toContain('/api/v1/runs/r1/artifacts/scene.json');
    expect(urls).toContain('/api/v1/runs/r1/artifacts/basemap.geojson');
    expect(urls).not.toContain('/api/v1/runs/r1/artifacts/plan.json');
    // Картинка покрытий в jsdom не декодируется: земля без неё, а не вечная загрузка.
    expect(h.create.mock.calls[0]?.[2]).toBeNull();
  });

  it('уход со страницы освобождает движок', async () => {
    mockApi(routes());
    const { router } = renderScene();
    const e = await ready();
    await act(() => router.navigate('/runs/r1'));
    expect(e.dispose).toHaveBeenCalled();
    expect(await screen.findByText('План прогона')).toBeVisible();
  });
});

describe('3D-вид: сцена готова', () => {
  it('сводка сцены, этажность, полосы и условности', async () => {
    h.state.world = world({
      fallback: true,
      treeStrips: [[{ x: 0, z: 0 }]],
      shrubStrips: [{ points: [] }, { points: [] }],
    });
    mockApi(routes());
    renderScene();
    await ready();
    const card = screen.getByRole('complementary', { name: 'Прогон' });
    const value = (term: string) => within(card).getByText(term).nextElementSibling?.textContent;
    expect(value('Деревья плана')).toBe('2');
    expect(value('Кустарник плана')).toBe('1');
    expect(value('Существующие')).toBe('1');
    expect(value('Здания')).toBe('2');
    expect(within(card).getByText(/Полосы насаждений: 1/)).toHaveTextContent(
      'Кустарниковые полосы: 2',
    );
    expect(
      within(card).getByText(/Этажность зданий: по подписи чертежа - 2, по признаку «жилое» - 1\./),
    ).toBeInTheDocument();
    expect(within(card).getByText(/Прогон сделан прежней версией сервиса/)).toBeInTheDocument();
    expect(screen.getByRole('note')).toHaveTextContent('Щёлкните по сцене');
    expect(
      within(screen.getByRole('toolbar', { name: 'Камера и снимки' })).getByText(/^\d+ м\/с$/),
    ).toBeInTheDocument();
  });

  it('без программной видеокарты качество не трогает, без неё - сразу «быстро»', async () => {
    h.state.software = true;
    mockApi(routes());
    renderScene();
    const e = await ready();
    expect(e.apply).toHaveBeenCalledWith(
      expect.objectContaining({ quality: 'low', enhanced: false }),
    );
    expect(screen.getByRole('radio', { name: 'быстро' })).toHaveAttribute('aria-checked', 'true');
  });

  it('ракурс из адреса ставит камеру при открытии и при смене адреса', async () => {
    window.history.replaceState(null, '', '/#view=10,20,30,0,0,walk');
    mockApi(routes());
    renderScene();
    const e = await ready();
    expect(e.setView).toHaveBeenCalledWith(
      expect.objectContaining({ x: 10, y: 20, z: 30 }),
      'walk',
    );
    window.history.replaceState(null, '', '/#view=1,2,3,0,0,fly');
    window.dispatchEvent(new HashChangeEvent('hashchange'));
    expect(e.setView).toHaveBeenLastCalledWith(
      expect.objectContaining({ x: 1, y: 2, z: 3 }),
      'fly',
    );
    act(() => {
      e.events.pose?.({ x: 5, y: 6, z: 7, yaw: 0, pitch: 0 }, 'fly');
    });
    expect(window.location.hash).toBe('#view=5,6,7,0,0,fly');
  });

  it('кадры в секунду, разрешение, прицел и наведение на растение', async () => {
    mockApi(routes());
    renderScene();
    const e = await ready();
    act(() => {
      e.events.frame?.({ fps: 42, drawCalls: 1, triangles: 1, scale: 0.5 });
      e.events.camera?.({ mode: 'walk', speed: 10, locked: true, touring: false });
    });
    expect(screen.getByText('шаг · 42 к/с · разрешение 50%')).toBeInTheDocument();
    expect(screen.queryByRole('note')).not.toBeInTheDocument();
    const hover: Hover = { plant: plant(), height: 4.25, crown: 3, distance: 12.5 };
    act(() => {
      e.events.hover?.(hover);
    });
    const status = screen.getByText('K - кадры этого растения').closest('[role="status"]');
    expect(status).toHaveAttribute('data-anchor', 'crosshair');
    expect(status).toHaveTextContent('дерево, Tilia cordata');
    expect(status).toHaveTextContent('высота 4,3 м, крона 3 м в возрасте 10 лет, 12,5 м от вас');
    act(() => {
      e.events.hover?.({ ...hover, plant: plant({ existing: true, type: 'existing_tree' }) });
    });
    expect(screen.getByText(/по съёмке/).closest('[role="status"]')).toHaveTextContent(
      'существующее дерево, Tilia cordata',
    );
    act(() => {
      e.events.hover?.(null);
    });
    expect(screen.queryByText('K - кадры этого растения')).not.toBeInTheDocument();
  });

  it('кнопки полосы управляют камерой', async () => {
    const user = userEvent.setup();
    mockApi(routes());
    renderScene();
    const e = await ready();
    await user.click(screen.getByRole('button', { name: /Общий вид/ }));
    expect(e.resetView).toHaveBeenCalled();
    await user.click(screen.getByRole('button', { name: /Облёт/ }));
    expect(e.startTour).toHaveBeenCalled();
    act(() => {
      e.events.camera?.({ mode: 'fly', speed: 10, locked: false, touring: true });
    });
    expect(screen.getByRole('button', { name: /Облёт/ })).toHaveAttribute('aria-pressed', 'true');
    await user.click(screen.getByRole('button', { name: /Облёт/ }));
    expect(e.stopTour).toHaveBeenCalled();
    await user.click(screen.getByRole('button', { name: /Пешеход/ }));
    expect(e.setMode).toHaveBeenCalledWith('walk');
    await user.click(screen.getByRole('button', { name: /Полёт/ }));
    expect(e.setMode).toHaveBeenCalledWith('fly');
    await user.click(screen.getByRole('button', { name: /Без панелей/ }));
    expect(screen.queryByRole('toolbar')).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Панели · H' }));
    expect(screen.getByRole('toolbar', { name: 'Камера и снимки' })).toBeVisible();
  });

  it('клавиши сцены: H, R, G, T; в поле ввода клавиши молчат', async () => {
    const user = userEvent.setup();
    mockApi(routes());
    renderScene();
    const e = await ready();
    await user.keyboard('r');
    expect(e.resetView).toHaveBeenCalledTimes(1);
    await user.keyboard('g');
    expect(e.setMode).toHaveBeenLastCalledWith('walk');
    e.freecam.mode = 'walk';
    await user.keyboard('g');
    expect(e.setMode).toHaveBeenLastCalledWith('fly');
    await user.keyboard('t');
    expect(e.startTour).toHaveBeenCalled();
    e.touring = true;
    await user.keyboard('t');
    expect(e.stopTour).toHaveBeenCalled();
    await user.keyboard('{Escape}');
    await user.keyboard('h');
    expect(screen.queryByRole('toolbar')).not.toBeInTheDocument();
    await user.keyboard('h');
    expect(screen.getByRole('toolbar')).toBeVisible();
    // Ползунок - не поле ввода, а чекбокс тоже: клавиша работает; текстовое поле - нет.
    const field = document.createElement('input');
    document.body.append(field);
    field.focus();
    await user.keyboard('r');
    expect(e.resetView).toHaveBeenCalledTimes(1);
    field.remove();
  });

  it('скорость с пульта уходит в движок', async () => {
    mockApi(routes());
    renderScene();
    const e = await ready();
    fireEvent.change(screen.getByLabelText(/Скорость полёта/), { target: { value: '100' } });
    expect(e.setSpeed).toHaveBeenCalledWith(expect.any(Number));
  });

  it('пульт меняет вид, город вокруг грузится один раз и подписывается', async () => {
    const user = userEvent.setup();
    const calls = mockApi(
      routes({
        '/api/v1/runs/r1/context': { source: 'OpenStreetMap', buildings: [] },
      }),
    );
    renderScene();
    const e = await ready();
    await user.click(screen.getByRole('radio', { name: 'зима' }));
    expect(e.apply).toHaveBeenLastCalledWith({ season: 'winter' });
    await user.click(screen.getByRole('checkbox', { name: /Город вокруг съёмки/ }));
    expect(e.apply).toHaveBeenLastCalledWith({ city: true });
    expect(
      await screen.findByText(/Город вокруг съёмки: 12 домов, дороги и стоянки квартала/),
    ).toHaveTextContent('Источник: OpenStreetMap.');
    await user.click(screen.getByRole('checkbox', { name: /Город вокруг съёмки/ }));
    await user.click(screen.getByRole('checkbox', { name: /Город вокруг съёмки/ }));
    expect(calls.filter((c) => c.url.endsWith('/context'))).toHaveLength(1);
  });

  it('города вокруг нет - причина в «что условно»', async () => {
    const user = userEvent.setup();
    mockApi(routes());
    renderScene();
    await ready();
    await user.click(screen.getByRole('checkbox', { name: /Город вокруг съёмки/ }));
    expect(await screen.findByText(/^Города вокруг нет:/)).toBeInTheDocument();
  });
});

describe('3D-вид: снимки', () => {
  it('снимок попадает в панель, ×2 снимает крупнее, удаление убирает карточку', async () => {
    const user = userEvent.setup();
    mockApi(routes({ [PHOTOS]: { available: false, reason: 'нет модели', photos: [] } }));
    renderScene();
    const e = await ready();
    const panel = screen.getByRole('region', { name: 'Снимки и фото' });
    await user.click(within(panel).getByRole('button', { name: /^Снимок/ }));
    expect(e.capture).toHaveBeenCalledWith(1);
    expect(await screen.findByText('Снимок - в панели «Снимки и фото» слева.')).toBeVisible();
    expect(within(panel).getByText('1920×1080')).toBeInTheDocument();
    expect(within(panel).getByRole('link', { name: 'скачать' })).toHaveAttribute(
      'download',
      expect.stringMatching(/^3d-Тестовая-улица-\d{8}-\d{6}\.png$/),
    );
    // Без модели фото снимок в нейросеть не отправить.
    expect(within(panel).queryByRole('button', { name: 'в фото ИИ' })).not.toBeInTheDocument();
    await user.click(within(panel).getByRole('button', { name: /крупнее ×2/ }));
    await user.keyboard('p');
    expect(e.capture).toHaveBeenLastCalledWith(2);
    await waitFor(() => {
      expect(within(panel).getAllByRole('button', { name: 'удалить' })).toHaveLength(2);
    });
    await user.click(within(panel).getAllByRole('button', { name: 'удалить' })[0] as HTMLElement);
    expect(within(panel).getAllByRole('button', { name: 'удалить' })).toHaveLength(1);
    expect(revokeUrl).toHaveBeenCalled();
  });

  it('сбой снимка - строка поверх сцены, сцена цела', async () => {
    const user = userEvent.setup();
    mockApi(routes());
    renderScene();
    const e = await ready();
    e.capture.mockRejectedValueOnce(new Error('кадр не отдался'));
    await user.click(screen.getByRole('button', { name: /^Снимок/ }));
    expect(await screen.findByText('кадр не отдался')).toBeVisible();
    expect(screen.getByRole('toolbar')).toBeVisible();
  });

  it('снимок в фото ИИ: холста нет в jsdom - сообщение, запроса нет', async () => {
    const user = userEvent.setup();
    const calls = mockApi(routes());
    renderScene();
    await ready();
    await user.click(screen.getByRole('button', { name: /^Снимок/ }));
    await user.click(await screen.findByRole('button', { name: 'в фото ИИ' }));
    expect(await screen.findByText('Браузер не дал холст для подготовки снимка')).toBeVisible();
    expect(posts(calls)).toHaveLength(0);
  });

  it('открыть снимок крупно и отправить его из просмотра', async () => {
    const user = userEvent.setup();
    const calls = mockApi(routes());
    renderScene();
    const e = await ready();
    await user.click(screen.getByRole('button', { name: /^Снимок/ }));
    await user.click(await screen.findByRole('button', { name: 'открыть' }));
    expect(e.setPaused).toHaveBeenLastCalledWith(true);
    const viewer = await screen.findByRole('dialog');
    expect(viewer).toHaveAttribute('open');
    // Холст 2D в jsdom не рисует: подгонка кадра под модель - на подменённом контексте.
    const drawImage = vi.fn();
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({
      drawImage,
    } as unknown as CanvasRenderingContext2D);
    vi.spyOn(HTMLCanvasElement.prototype, 'toBlob').mockImplementation((done) => {
      done(new Blob(['fit'], { type: 'image/png' }));
    });
    await user.click(within(viewer).getByRole('button', { name: 'в фото ИИ' }));
    await waitFor(() => {
      expect(posts(calls)).toHaveLength(1);
    });
    expect(drawImage).toHaveBeenCalledWith(expect.anything(), 0, 0, 1920, 1080, 0, 0, 1536, 864);
    expect(formOf(posts(calls)[0]).get('shot')).toMatch(/^Снимок \d\d:\d\d$/);
  });
});

describe('3D-вид: фото нейросетью', () => {
  it('фото с текущего вида уходит в очередь со всеми настройками', async () => {
    const user = userEvent.setup();
    const calls = mockApi(routes());
    renderScene();
    const e = await ready();
    const panel = screen.getByRole('region', { name: 'Снимки и фото' });
    await user.click(within(panel).getByRole('button', { name: /фон и деревья/ }));
    await user.click(within(panel).getByRole('button', { name: /новые фасады/ }));
    await user.click(within(panel).getByRole('button', { name: /^Фото ИИ/ }));
    expect(e.viewShot).toHaveBeenCalled();
    expect(await screen.findByText(/Кадр ушёл в нейросеть/)).toBeVisible();
    const form = formOf(posts(calls)[0]);
    expect(form.get('scenery')).toBe('true');
    expect(form.get('modern')).toBe('false');
    expect(form.get('viewpoint')).toBe('ground');
    expect(form.get('species')).toBe('Tilia cordata');
    expect(form.get('shrubs')).toBe('Spiraea japonica');
    expect(form.get('buildings')).toBe('false');
    expect(form.get('season')).toBe('summer');
    expect(form.get('hour')).toBe('11');
    expect(form.get('shot') as string).toMatch(/^Вид из 3D, \d\d:\d\d$/);
    expect(form.get('prompt')).toBe('');
  });

  it('клавиша F и отказ сервера - текст ошибки строкой', async () => {
    const user = userEvent.setup();
    mockApi(
      routes({
        [`POST ${PHOTOS}`]: () =>
          new Response(
            JSON.stringify({ title: 'Conflict', status: 409, detail: 'очередь заполнена' }),
            { status: 409, headers: { 'content-type': 'application/problem+json' } },
          ),
      }),
    );
    renderScene();
    await ready();
    await user.keyboard('f');
    expect(await screen.findByText(/очередь заполнена/)).toBeVisible();
  });

  it('сбой кадра вида - сообщение', async () => {
    const user = userEvent.setup();
    mockApi(routes());
    renderScene();
    const e = await ready();
    e.viewShot.mockRejectedValueOnce(new Error('кадр вида не снят'));
    await user.click(screen.getByRole('button', { name: /^Фото ИИ/ }));
    expect(await screen.findByText('кадр вида не снят')).toBeVisible();
  });

  it('без модели фото кнопка неактивна и объясняет почему', async () => {
    mockApi(
      routes({ [PHOTOS]: { available: false, reason: 'модели не смонтированы', photos: [] } }),
    );
    renderScene();
    await ready();
    expect(screen.getByRole('button', { name: /^Фото ИИ/ })).toBeDisabled();
    expect(screen.getByText(/Фото нейросетью недоступно: модели не смонтированы/)).toBeVisible();
  });

  it('свой промпт из окна уходит вместе с кадром', async () => {
    const user = userEvent.setup();
    const calls = mockApi(
      routes({
        [`${PHOTOS}/prompt?scenery=false&modern=true&season=summer&hour=11`]: {
          text: 'улица летом',
          negative: 'люди',
        },
      }),
    );
    renderScene();
    await ready();
    await user.click(screen.getByRole('button', { name: /промпт/ }));
    const dialog = await screen.findByRole('dialog', { name: 'Промпт фото ИИ' });
    const text = await within(dialog).findByDisplayValue('улица летом');
    await user.clear(text);
    await user.type(text, 'аллея осенью');
    await user.click(within(dialog).getByRole('button', { name: 'готово' }));
    expect(screen.getByRole('button', { name: /свой промпт/ })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /^Фото ИИ/ }));
    await waitFor(() => {
      expect(posts(calls)).toHaveLength(1);
    });
    expect(formOf(posts(calls)[0]).get('prompt')).toBe('аллея осенью');
  });

  it('фото с сервера: удалить после подтверждения, отказ - строкой', async () => {
    const user = userEvent.setup();
    const confirm = vi.spyOn(window, 'confirm').mockReturnValueOnce(false).mockReturnValue(true);
    const calls = mockApi(
      routes({
        [PHOTOS]: { available: true, reason: null, photos: [photo()] },
        [`DELETE ${PHOTOS}/ph1`]: () =>
          new Response(JSON.stringify({ detail: 'фото ещё рисуется' }), { status: 409 }),
      }),
    );
    renderScene();
    await ready();
    const panel = screen.getByRole('region', { name: 'Снимки и фото' });
    const remove = await within(panel).findByRole('button', { name: 'удалить' });
    await user.click(remove);
    expect(calls.filter((c) => c.method === 'DELETE')).toHaveLength(0);
    await user.click(remove);
    expect(confirm).toHaveBeenCalledTimes(2);
    expect(await screen.findByText('фото ещё рисуется')).toBeVisible();
    expect(calls.filter((c) => c.method === 'DELETE')).toHaveLength(1);
  });

  it('удалённое фото перечитывает список', async () => {
    const user = userEvent.setup();
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    const calls = mockApi(
      routes({
        [PHOTOS]: { available: true, reason: null, photos: [photo()] },
        [`DELETE ${PHOTOS}/ph1`]: () => new Response(null, { status: 204 }),
      }),
    );
    renderScene();
    await ready();
    const panel = screen.getByRole('region', { name: 'Снимки и фото' });
    await user.click(await within(panel).findByRole('button', { name: 'удалить' }));
    await waitFor(() => {
      expect(calls.filter((c) => c.url === PHOTOS && c.method === 'GET')).toHaveLength(2);
    });
  });
});

describe('3D-вид: галерея кадров', () => {
  it('кадры улицы: фото по кадру, переход в 3D с ракурса кадра', async () => {
    const user = userEvent.setup();
    const calls = mockApi(routes());
    renderScene();
    const e = await ready();
    await user.click(screen.getByRole('button', { name: /^Кадры/ }));
    const gallery = await screen.findByRole('dialog', { name: 'Кадры улицы' });
    expect(e.planShots).toHaveBeenCalledWith({ kind: 'street' });
    expect(e.renderViews).toHaveBeenCalledWith([expect.objectContaining({ y: 30 })], 1536, 864);
    expect(e.setPaused).toHaveBeenLastCalledWith(true);
    expect(within(gallery).getByRole('img', { name: 'Кадры улицы. Сверху' })).toBeVisible();
    // У галереи улицы перехода «кадры улицы» нет: она сама и есть кадры улицы.
    expect(within(gallery).queryByRole('button', { name: 'кадры улицы' })).not.toBeInTheDocument();
    await user.click(within(gallery).getByRole('button', { name: 'фото' }));
    await waitFor(() => {
      expect(posts(calls)).toHaveLength(1);
    });
    expect(formOf(posts(calls)[0]).get('shot')).toBe('Кадры улицы. Сверху');
    await user.click(within(gallery).getByRole('button', { name: 'в 3D' }));
    expect(e.setView).toHaveBeenLastCalledWith(expect.objectContaining({ y: 30 }), 'fly');
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(e.setPaused).toHaveBeenLastCalledWith(false);
  });

  it('K над растением - кадры этого растения, из них - к кадрам улицы', async () => {
    const user = userEvent.setup();
    mockApi(routes());
    renderScene();
    const e = await ready();
    act(() => {
      e.events.hover?.({ plant: plant(), height: 4, crown: 3, distance: 5 });
    });
    await user.keyboard('k');
    const gallery = await screen.findByRole('dialog', { name: 'Кадры: № 1. Липа мелколистная' });
    expect(e.planShots).toHaveBeenCalledWith({ kind: 'plant', id: 'p1' });
    await user.click(within(gallery).getByRole('button', { name: 'кадры улицы' }));
    expect(await screen.findByRole('dialog', { name: 'Кадры улицы' })).toBeVisible();
    await user.click(screen.getByRole('button', { name: /к 3D-виду/ }));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('пустая сцена и сбой отрисовки кадров - текст в галерее', async () => {
    const user = userEvent.setup();
    mockApi(routes());
    renderScene();
    const e = await ready();
    e.planShots.mockReturnValueOnce([]);
    await user.keyboard('k');
    expect(await screen.findByText('В сцене нет посадок.')).toBeVisible();
    await user.click(screen.getByRole('button', { name: /к 3D-виду/ }));
    e.renderViews.mockRejectedValueOnce(new Error('видеопамять кончилась'));
    await user.click(screen.getByRole('button', { name: /^Кадры/ }));
    expect(await screen.findByText('видеопамять кончилась')).toBeVisible();
  });

  it('ссылка с карты ?plant= открывает кадры посадки сразу', async () => {
    mockApi(routes());
    renderScene('/runs/r1/3d?plant=p2');
    expect(
      await screen.findByRole('dialog', { name: 'Кадры: № 2. Липа мелколистная' }),
    ).toBeVisible();
    expect(engine().planShots).toHaveBeenCalledWith({ kind: 'plant', id: 'p2' });
  });

  it('?plant= с посадкой, которой нет в сцене, и ?shots=street', async () => {
    mockApi(routes());
    renderScene('/runs/r1/3d?plant=zz');
    expect(await screen.findByRole('dialog', { name: 'Кадры посадки' })).toBeVisible();
  });

  it('?shots=street открывает кадры улицы', async () => {
    mockApi(routes());
    renderScene('/runs/r1/3d?shots=street');
    expect(await screen.findByRole('dialog', { name: 'Кадры улицы' })).toBeVisible();
  });
});
