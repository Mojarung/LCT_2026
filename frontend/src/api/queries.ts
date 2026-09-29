/* Данные сервера для страниц. Справочники не устаревают за сессию, прогон опрашивается,
 * пока идёт, артефакты прогона неизменны до пересборки. */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { artifactUrl, getJson, postForm, runPollInterval } from './client';
import type {
  MetaOut,
  PhotoListOut,
  PhotoOut,
  PromptOut,
  ProfileOut,
  RunListOut,
  RunOut,
  StreetOut,
} from './types';

export const keys = {
  meta: ['meta'] as const,
  streets: ['streets'] as const,
  profile: (name: string) => ['profile', name] as const,
  runs: (limit: number) => ['runs', limit] as const,
  run: (id: string) => ['run', id] as const,
  artifacts: (id: string) => ['artifact', id] as const,
  artifact: (id: string, name: string) => ['artifact', id, name] as const,
  photos: (id: string) => ['photos', id] as const,
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

/** Опрос фото, пока модель рисует: кадр считается минуту-две. */
export const PHOTO_POLL_MS = 3000;

const photosUrl = (runId: string) => `/api/v1/runs/${encodeURIComponent(runId)}/photos`;

/** Фото прогона и можно ли их делать на этом сервере. Опрос - пока есть незаконченные. */
export function usePhotos(runId: string, enabled: boolean) {
  return useQuery({
    queryKey: keys.photos(runId),
    queryFn: () => getJson<PhotoListOut>(photosUrl(runId), { cache: 'no-store' }),
    enabled,
    refetchInterval: (query) =>
      query.state.data?.photos.some((p) => p.state === 'queued' || p.state === 'running')
        ? PHOTO_POLL_MS
        : false,
  });
}

export interface PhotoRequest {
  image: Blob;
  scenery: boolean;
  season: string;
  hour: number;
  viewpoint: 'aerial' | 'ground';
  species: string[];
  shrubs: string[];
  /** Подпись кадра: по ней галерея находит фото своего кадра. */
  shot: string;
  /** Современные московские фасады вместо условных. */
  modern: boolean;
  /** Свой промпт из редактора; пусто - сервис соберёт сам. */
  prompt: string;
  negative: string;
}

/** Поставить кадр в очередь модели. */
export function useCreatePhoto(runId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (req: PhotoRequest) => {
      const form = new FormData();
      form.append('image', req.image, 'shot.png');
      form.append('scenery', String(req.scenery));
      form.append('season', req.season);
      form.append('hour', String(req.hour));
      form.append('viewpoint', req.viewpoint);
      form.append('species', req.species.join(','));
      form.append('shrubs', req.shrubs.join(','));
      form.append('shot', req.shot);
      form.append('modern', String(req.modern));
      form.append('prompt', req.prompt);
      form.append('negative', req.negative);
      return postForm<PhotoOut>(photosUrl(runId), form);
    },
    onSuccess: () => client.invalidateQueries({ queryKey: keys.photos(runId) }),
  });
}

export interface PromptParams {
  scenery: boolean;
  modern: boolean;
  season: string;
  hour: number;
}

/** Промпт, который сервис соберёт при этих настройках: основа редактора промпта. */
export function usePromptPreview(runId: string, params: PromptParams, enabled: boolean) {
  const query = new URLSearchParams({
    scenery: String(params.scenery),
    modern: String(params.modern),
    season: params.season,
    hour: String(params.hour),
  });
  return useQuery({
    queryKey: ['prompt', runId, params],
    queryFn: () => getJson<PromptOut>(`${photosUrl(runId)}/prompt?${query.toString()}`),
    enabled,
    staleTime: Infinity,
  });
}

/** Удалить фото с сервера; фото в работе сервер не удаляет (409). */
export function useDeletePhoto(runId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (photoId: string) => {
      const response = await fetch(`${photosUrl(runId)}/${encodeURIComponent(photoId)}`, {
        method: 'DELETE',
      });
      if (!response.ok && response.status !== 404) {
        const body = (await response.json().catch(() => ({}))) as { detail?: string };
        throw new Error(body.detail ?? `Не удалось удалить фото: HTTP ${String(response.status)}`);
      }
    },
    onSuccess: () => client.invalidateQueries({ queryKey: keys.photos(runId) }),
  });
}
