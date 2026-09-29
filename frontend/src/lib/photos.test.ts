import { describe, expect, it } from 'vitest';

import type { PhotoOut } from '../api/types';
import { coverCrop, expectedSeconds, PHOTO_SECONDS_DEFAULT, photoProgress } from './photos';

function photo(patch: Partial<PhotoOut>): PhotoOut {
  return {
    id: 'a',
    state: 'queued',
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
    created_at: '2026-09-29T10:00:00Z',
    started_at: null,
    finished_at: null,
    seconds: null,
    error: null,
    upscaled: false,
    source_url: '/s',
    photo_url: null,
    raw_url: null,
    ...patch,
  };
}

describe('coverCrop', () => {
  it('cuts the sides of a wide screen to 16:9', () => {
    const crop = coverCrop(3200, 1200, 1024, 576);
    expect(crop.sh).toBe(1200);
    expect(crop.sw).toBe(2133);
    expect(crop.sx).toBe(534);
    expect(crop.sy).toBe(0);
  });

  it('cuts the top and bottom of a tall screen', () => {
    const crop = coverCrop(1000, 1000, 1024, 576);
    expect(crop.sw).toBe(1000);
    expect(crop.sh).toBe(563);
    expect(crop.sy).toBe(219);
  });
});

describe('expectedSeconds', () => {
  it('takes the median of finished photos and falls back without them', () => {
    expect(expectedSeconds([])).toBe(PHOTO_SECONDS_DEFAULT);
    expect(
      expectedSeconds([
        photo({ state: 'succeeded', seconds: 70 }),
        photo({ state: 'succeeded', seconds: 90 }),
        photo({ state: 'succeeded', seconds: 80 }),
        photo({ state: 'failed', seconds: 5 }),
      ]),
    ).toBe(80);
  });
});

describe('photoProgress', () => {
  const now = Date.parse('2026-09-29T10:01:00Z');

  it('counts the jobs ahead in the queue', () => {
    const first = photo({ id: 'r', state: 'running', created_at: '2026-09-29T09:59:00Z' });
    const mine = photo({ id: 'm', created_at: '2026-09-29T10:00:00Z' });
    expect(photoProgress(mine, [first, mine], now, 80).label).toBe('в очереди, перед ним 1');
  });

  it('fills the bar by elapsed time and never reaches the end before the answer', () => {
    const running = photo({ state: 'running', started_at: '2026-09-29T10:00:20Z' });
    const p = photoProgress(running, [running], now, 80);
    expect(p.share).toBeCloseTo(0.5);
    expect(p.label).toBe('модель рисует, осталось около 40 с');
    const late = photoProgress(running, [running], now + 300_000, 80);
    expect(late.share).toBe(0.95);
    expect(late.label).toBe('модель дорисовывает');
  });

  it('shows the failure reason', () => {
    const failed = photo({ state: 'failed', error: 'out of memory' });
    expect(photoProgress(failed, [failed], now, 80).label).toBe('не удалось: out of memory');
  });
});
