/* Данные сервера для страниц. Справочники не устаревают за сессию, прогон опрашивается,
 * пока идёт, артефакты прогона неизменны до пересборки. */

import { useQuery } from '@tanstack/react-query';

import { artifactUrl, getJson, runPollInterval } from './client';
import type { MetaOut, ProfileOut, RunListOut, RunOut, StreetOut } from './types';

export const keys = {
  meta: ['meta'] as const,
  streets: ['streets'] as const,
  profile: (name: string) => ['profile', name] as const,
  runs: (limit: number) => ['runs', limit] as const,
  run: (id: string) => ['run', id] as const,
  artifacts: (id: string) => ['artifact', id] as const,
  artifact: (id: string, name: string) => ['artifact', id, name] as const,
};

export function useMeta() {
  return useQuery({
    queryKey: keys.meta,
    queryFn: () => getJson<MetaOut>('/api/v1/meta'),
    staleTime: Infinity,
  });
}

export function useStreets() {
  return useQuery({
    queryKey: keys.streets,
    queryFn: () => getJson<StreetOut[]>('/api/v1/streets'),
    staleTime: Infinity,
  });
}

export function useProfile(name: string | undefined) {
  return useQuery({
    queryKey: keys.profile(name ?? ''),
    queryFn: () => getJson<ProfileOut>(`/api/v1/profiles/${encodeURIComponent(name ?? '')}`),
    enabled: Boolean(name),
    staleTime: Infinity,
  });
}

export function useRuns(limit: number) {
  return useQuery({
    queryKey: keys.runs(limit),
    queryFn: async () => (await getJson<RunListOut>(`/api/v1/runs?limit=${limit}`)).items,
  });
}

/** Прогон с опросом раз в две секунды, пока он в очереди или считается. no-store: ответ о
 *  ходе расчёта из кэша браузера - это вчерашний ход. */
export function useRun(id: string) {
  return useQuery({
    queryKey: keys.run(id),
    queryFn: () => getJson<RunOut>(`/api/v1/runs/${encodeURIComponent(id)}`, { cache: 'no-store' }),
    refetchInterval: (query) => runPollInterval(query.state.data?.state),
    staleTime: 0,
  });
}

/** Артефакт прогона. Не force-cache: он переиспользует и ошибочные ответы, и 404, полученный
 *  до конца прогона, залипал бы навсегда. */
export function useArtifact<T>(runId: string, name: string, enabled: boolean) {
  return useQuery({
    queryKey: keys.artifact(runId, name),
    queryFn: () => getJson<T>(artifactUrl(runId, name)),
    enabled,
    staleTime: Infinity,
  });
}
