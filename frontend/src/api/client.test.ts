import { describe, expect, it, vi } from 'vitest';

import { ApiError, getJson, postForm, postJson, runPollInterval, shouldRetry } from './client';

const problem = (status: number, detail: string) =>
  new Response(
    JSON.stringify({ type: 'about:blank', title: 'Unprocessable Content', status, detail }),
    {
      status,
      headers: { 'content-type': 'application/problem+json' },
    },
  );

describe('клиент API', () => {
  it('ошибка RFC 9457 несёт то, что сказал сервер', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(problem(422, 'Улицы x нет в каталоге'));

    await expect(getJson('/api/v1/runs')).rejects.toMatchObject({
      status: 422,
      detail: 'Улицы x нет в каталоге',
      message: 'Улицы x нет в каталоге',
    });
  });

  it('ответ без JSON - статус и текст, а не «Unexpected token»', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(
      new Response('Internal Server Error', { status: 500, statusText: 'Internal Server Error' }),
    );

    const error = await getJson('/api/v1/meta').catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ status: 500, detail: 'Internal Server Error' });
  });

  it('успешный ответ разбирается как JSON', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(Response.json({ status: 'ok', version: '0.1.0' }));

    await expect(getJson('/api/v1/health')).resolves.toEqual({ status: 'ok', version: '0.1.0' });
  });

  it('форма уходит multipart: content-type с границей ставит сам браузер', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(Response.json({ id: 'r1' }));
    const form = new FormData();
    form.set('street', '07-test-street');

    await postForm('/api/v1/runs', form);

    const [url, init] = vi.mocked(fetch).mock.calls[0] ?? [];
    expect(url).toBe('/api/v1/runs');
    expect(init?.method).toBe('POST');
    expect(init?.body).toBe(form);
    expect(new Headers(init?.headers).has('content-type')).toBe(false);
  });

  it('JSON уходит с content-type application/json', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(Response.json({ placements: 1 }));

    await postJson('/api/v1/runs/r1/edits', { edits: [] });

    const [, init] = vi.mocked(fetch).mock.calls[0] ?? [];
    expect(new Headers(init?.headers).get('content-type')).toBe('application/json');
    expect(init?.body).toBe('{"edits":[]}');
  });
});

describe('повторы и опрос', () => {
  it('ошибку клиента не повторяем, сбой сервера - ещё раз', () => {
    expect(shouldRetry(0, new ApiError(404, 'Not Found', ''))).toBe(false);
    expect(shouldRetry(0, new ApiError(422, '', 'bad'))).toBe(false);
    expect(shouldRetry(0, new ApiError(503, '', ''))).toBe(true);
    expect(shouldRetry(0, new TypeError('Failed to fetch'))).toBe(true);
    expect(shouldRetry(2, new ApiError(503, '', ''))).toBe(false);
  });

  it('прогон опрашивается раз в две секунды, пока идёт, и перестаёт, когда кончился', () => {
    expect(runPollInterval('queued')).toBe(2000);
    expect(runPollInterval('running')).toBe(2000);
    expect(runPollInterval('succeeded')).toBe(false);
    expect(runPollInterval('failed')).toBe(false);
    expect(runPollInterval(undefined)).toBe(2000);
  });
});
