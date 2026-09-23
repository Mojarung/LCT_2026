import { QueryClient } from '@tanstack/react-query';

/** Клиент данных приложения. Фокус окна ничего не перезапрашивает: на защите окно то и дело
 *  теряет фокус (переключение на CAD и обратно), и карта не должна перезагружаться от этого. */
export function makeQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: 1, refetchOnWindowFocus: false, staleTime: 30_000 },
    },
  });
}
