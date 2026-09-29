import { describe, expect, it } from 'vitest';

import type { PhotoOut } from '../api/types';
import { mediaBadge, mediaItems, mediaTitle, type Shot } from './media';

const shot = (id: number): Shot => ({
  id,
  url: `blob:${String(id)}`,
  name: `3d-${String(id)}.png`,
  width: 3200,
  height: 1800,
  blob: new Blob(),
  viewpoint: 'aerial',
  trees: [],
  shrubs: [],
});

const photo = (id: string, created: string, patch: Partial<PhotoOut> = {}): PhotoOut => ({
  id,
  state: 'succeeded',
  scenery: false,
  season: 'summer',
  hour: 11,
  viewpoint: 'aerial',
  species: [],
  shrubs: [],
  shot: '',
  modern: false,
  custom: false,
  width: 1024,
  height: 576,
  created_at: created,
  started_at: null,
  finished_at: null,
  seconds: 80,
  error: null,
  upscaled: true,
  source_url: '/s',
  photo_url: '/p',
  raw_url: '/r',
  ...patch,
});

describe('mediaItems', () => {
  it('mixes snapshots and photos, newest first', () => {
    const items = mediaItems(
      [shot(Date.parse('2026-09-29T10:05:00Z'))],
      [photo('a', '2026-09-29T10:10:00Z'), photo('b', '2026-09-29T10:00:00Z')],
    );
    expect(items.map((i) => i.key)).toEqual([
      'pa',
      `s${String(Date.parse('2026-09-29T10:05:00Z'))}`,
      'pb',
    ]);
  });
});

describe('mediaTitle and mediaBadge', () => {
  it('names the kind and the mode', () => {
    const [snap] = mediaItems([shot(Date.parse('2026-09-29T10:05:00Z'))], []);
    const [ai] = mediaItems(
      [],
      [photo('a', '2026-09-29T10:10:00Z', { shot: 'Участок 1 из 3', scenery: true })],
    );
    const [bad] = mediaItems([], [photo('b', '2026-09-29T10:10:00Z', { state: 'failed' })]);
    expect(snap && mediaBadge(snap)).toBe('снимок');
    expect(snap && mediaTitle(snap)).toMatch(/^Снимок \d\d:\d\d$/);
    expect(ai && mediaTitle(ai)).toBe('Участок 1 из 3');
    expect(ai && mediaBadge(ai)).toBe('ИИ + фон');
    expect(bad && mediaBadge(bad)).toBe('ошибка');
  });
});
