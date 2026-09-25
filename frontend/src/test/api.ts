/* Подмена API в тестах: ответы по методу и адресу, журнал запросов для проверок. */

import { vi } from 'vitest';

import type { MetaOut, ProfileOut, RunOut, StreetOut } from '../api/types';

export interface Call {
  method: string;
  url: string;
  init: RequestInit | undefined;
}

type Responder = (call: Call) => Response | Promise<Response>;

const notFound = (key: string) =>
  new Response(JSON.stringify({ title: 'Not Found', status: 404, detail: `нет в тесте: ${key}` }), {
    status: 404,
    headers: { 'content-type': 'application/problem+json' },
  });

/** Ключ - «МЕТОД /адрес» или просто «/адрес» для GET. Значение - тело JSON или функция,
 *  возвращающая Response. Неописанный адрес получает 404, как у сервера. */
export function mockApi(routes: Record<string, unknown>): Call[] {
  const calls: Call[] = [];
  vi.mocked(fetch).mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
    const method = (init?.method ?? 'GET').toUpperCase();
    const call = { method, url, init };
    calls.push(call);
    const key = `${method} ${url}`;
    const handler = key in routes ? routes[key] : method === 'GET' ? routes[url] : undefined;
    if (handler === undefined) return Promise.resolve(notFound(key));
    if (typeof handler === 'function') return Promise.resolve((handler as Responder)(call));
    return Promise.resolve(Response.json(handler));
  });
  return calls;
}

export const meta: MetaOut = {
  version: '0.1.0',
  default_profile: 'strict',
  profiles: ['barriers', 'no_utilities', 'shrubs', 'strict'],
  result_layers: ['GREEN_TREES', 'GREEN_SHRUBS', 'GREEN_REJECT'],
  rules: { total: 76, verified: 75, fingerprint: 'abc' },
  species: [
    {
      code: 'tilia_cordata',
      name_ru: 'Липа мелколистная',
      name_lat: 'Tilia cordata',
      crown_diameter_m: 4,
    },
  ],
  converters: [{ name: 'libredwg', available: true }],
};

export const streets: StreetOut[] = [
  { slug: '07-test-street', number: 7, title: 'Тестовая улица', files: 2, size_mb: 12.4 },
];

export const strict: ProfileOut = {
  name: 'strict',
  planting_type: 'tree',
  spacing_m: 5,
  modes: ['alley', 'lawn', 'fill'],
  root_barriers: false,
  shrub_groups: true,
  shrub_rows: true,
  curb_hedges: true,
  understory: true,
  shrub_fill: true,
};

export const shrubs: ProfileOut = {
  ...strict,
  name: 'shrubs',
  planting_type: 'shrub',
  spacing_m: 1,
  modes: ['alley', 'lawn'],
};

export function run(overrides: Partial<RunOut> = {}): RunOut {
  return {
    id: 'r1',
    state: 'succeeded',
    source_name: 'Тестовая улица.dxf',
    profile: 'strict',
    overrides: {},
    created_at: '2026-09-23T09:15:00Z',
    updated_at: '2026-09-23T09:16:00Z',
    error: null,
    summary: { placements: 302, needs_approval: 0, rejections: 161, integrity_ok: true },
    artifacts: [],
    progress: null,
    ...overrides,
  };
}

/** Справочники консоли: мета, улицы, профили и пустой список прогонов. */
export function consoleRoutes(options: { streets?: StreetOut[] } = {}) {
  return {
    '/api/v1/meta': meta,
    '/api/v1/streets': options.streets ?? streets,
    '/api/v1/profiles/strict': strict,
    '/api/v1/profiles/shrubs': shrubs,
    '/api/v1/runs?limit=12': { items: [] },
  };
}
