import { QueryClientProvider } from '@tanstack/react-query';
import { render } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router';

import { makeQueryClient } from '../api/queryClient';
import { routes } from '../router';

/** Приложение целиком на адресе path: те же маршруты, что в браузере, но история в памяти.
 *  Роутер возвращается, чтобы тест мог проверить, куда увёл переход. */
export function renderApp(path: string) {
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  const client = makeQueryClient();
  client.setDefaultOptions({ queries: { retry: false, refetchOnWindowFocus: false } });
  const view = render(
    <QueryClientProvider client={client}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return { ...view, router, client };
}
