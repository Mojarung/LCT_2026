/* Параметры прогона поверх профиля: форма шлёт только то, что человек изменил.
 *
 * Раньше форма всегда отправляла свой шаг 5 м и все галочки, и выбор профиля barriers или
 * shrubs молча терял смысл (находка аудита 23.09). Теперь форма заполняется значениями
 * выбранного профиля из GET /api/v1/profiles/{name}, а в overrides уходит разница. */

import type { ProfileOut } from '../api/types';
import { plain } from './format';

export type Switch =
  | 'root_barriers'
  | 'shrub_groups'
  | 'shrub_rows'
  | 'curb_hedges'
  | 'understory'
  | 'shrub_fill'
  | 'lawns';

export const SWITCHES: readonly Switch[] = [
  'shrub_groups',
  'shrub_rows',
  'curb_hedges',
  'understory',
  'shrub_fill',
  'lawns',
  'root_barriers',
];

/** Параметры профиля из GET /api/v1/profiles/{name}. */
export type ProfileParams = ProfileOut;

export interface RunFormValues {
  spacing_m: number;
  fill: boolean;
  switches: Record<Switch, boolean>;
}

export function formDefaults(profile: ProfileParams): RunFormValues {
  return {
    spacing_m: profile.spacing_m,
    fill: profile.modes.includes('fill'),
    switches: {
      root_barriers: profile.root_barriers,
      shrub_groups: profile.shrub_groups,
      shrub_rows: profile.shrub_rows,
      curb_hedges: profile.curb_hedges,
      understory: profile.understory,
      shrub_fill: profile.shrub_fill,
      lawns: profile.lawns,
    },
  };
}

/** «Продвинутый» JSON поверх профиля. Сообщения те же, что у сервера (parse_overrides). */
export function parseAdvanced(raw: string): Record<string, unknown> {
  if (!raw.trim()) return {};
  let value: unknown;
  try {
    value = JSON.parse(raw);
  } catch (error) {
    throw new Error(`overrides: некорректный JSON: ${(error as Error).message}`, { cause: error });
  }
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    throw new Error('overrides: ожидается JSON-объект');
  }
  return value as Record<string, unknown>;
}

export function diffOverrides(
  profile: ProfileParams,
  form: RunFormValues,
  advanced: string,
): Record<string, unknown> {
  const values = parseAdvanced(advanced);
  if (form.spacing_m !== profile.spacing_m) values.spacing_m = form.spacing_m;
  for (const name of SWITCHES) {
    if (form.switches[name] !== profile[name]) values[name] = form.switches[name];
  }
  const fillNow = profile.modes.includes('fill');
  if (form.fill !== fillNow && !('modes' in values)) {
    values.modes = form.fill
      ? [...profile.modes, 'fill']
      : profile.modes.filter((mode) => mode !== 'fill');
  }
  return values;
}

/** Короткие имена параметров для шапки прогона: там стоят только отличия от профиля, и
 *  сырые ключи JSON («root_barriers: true») эксперту ничего не говорят. */
const PARAM_RU: Record<string, string> = {
  modes: 'приёмы',
  root_barriers: 'барьеры',
  shrub_groups: 'группы кустарника',
  shrub_rows: 'ряд у борта',
  curb_hedges: 'изгородь',
  understory: 'подлесок',
  shrub_fill: 'кустарник на газоне',
  lawns: 'газоны',
  species_code: 'вид',
  planting_type: 'тип посадки',
};
const MODE_RU: Record<string, string> = { alley: 'аллея', lawn: 'газон', fill: 'добор' };

function valueText(value: unknown): string {
  if (typeof value === 'boolean') return value ? 'да' : 'нет';
  if (typeof value === 'number') return plain(value);
  if (Array.isArray(value))
    return value.map((item) => MODE_RU[String(item)] ?? String(item)).join(', ');
  return typeof value === 'string' ? value : JSON.stringify(value);
}

export function overrideLabel(key: string, value: unknown): string {
  if (key === 'spacing_m' && typeof value === 'number') return `шаг ${plain(value)} м`;
  return `${PARAM_RU[key] ?? key}: ${valueText(value)}`;
}
