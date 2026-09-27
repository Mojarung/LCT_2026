/* Клиент JSON API сервиса. Пути относительные: интерфейс и API живут на одном адресе. */

/** Ошибка ответа. Сервер отдаёт ошибки в формате RFC 9457 (application/problem+json), и
 *  человеку показывается его detail - «Улицы x нет в каталоге», а не «HTTP 422». */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly title: string,
    readonly detail: string,
  ) {
    super(detail || title || `HTTP ${status}`);
    this.name = 'ApiError';
  }
}

async function failure(response: Response): Promise<ApiError> {
  const type = response.headers.get('content-type') ?? '';
  if (type.includes('json')) {
    try {
      const body = (await response.json()) as { title?: unknown; detail?: unknown };
      const detail =
        typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail ?? '');
      const title = typeof body.title === 'string' ? body.title : '';
      return new ApiError(response.status, title, detail);
    } catch {
      // Заявлен JSON, а пришло что-то другое: ниже вернём статус.
    }
  }
  const text = await response.text().catch(() => '');
  return new ApiError(response.status, response.statusText, text.slice(0, 300));
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init);
  if (!response.ok) throw await failure(response);
  return (await response.json()) as T;
}

export function getJson<T>(path: string, init?: RequestInit): Promise<T> {
  return request<T>(path, init);
}

/** Multipart-форма: заголовок с границей частей ставит сам браузер, руками его не задаём. */
export function postForm<T>(path: string, form: FormData): Promise<T> {
  return request<T>(path, { method: 'POST', body: form });
}

export function postJson<T>(path: string, body: unknown): Promise<T> {
  return request<T>(path, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body),
  });
}

export const artifactUrl = (runId: string, name: string): string =>
  `/api/v1/runs/${encodeURIComponent(runId)}/artifacts/${encodeURIComponent(name)}`;

/** Ошибку клиента (4xx) повторять бессмысленно - ответ будет тем же. Сбой сервера или сети
 *  повторяем ещё раз: на стенде сервис бывает занят тяжёлым прогоном. */
export function shouldRetry(failures: number, error: unknown): boolean {
  if (error instanceof ApiError && error.status < 500) return false;
  return failures < 2;
}

export const POLL_MS = 2000;

/** Прогон опрашивается, пока идёт; неизвестное состояние - тоже опрос, а не тишина. */
export function runPollInterval(state: string | undefined): number | false {
  return state === 'succeeded' || state === 'failed' ? false : POLL_MS;
}
