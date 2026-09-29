import { describe, expect, it } from 'vitest';

import { orderProfiles, PROFILES, profileTitle } from './profiles';

/** Имена профилей прямо из config/profiles: словарь обязан идти за папкой. */
const files = Object.keys(
  import.meta.glob('../../../config/profiles/*.yaml', { query: '?raw', eager: true }),
).map((path) => path.replace(/^.*\/(.+)\.yaml$/, '$1'));

describe('профили по-русски', () => {
  it('у каждого профиля из config/profiles есть название и пояснение, лишних нет', () => {
    expect(files.length).toBeGreaterThanOrEqual(5);
    expect(Object.keys(PROFILES).sort()).toEqual([...files].sort());
    for (const name of files) {
      expect(PROFILES[name]?.title).toMatch(/[А-Яа-я]/);
      expect(PROFILES[name]?.text.length).toBeGreaterThan(20);
    }
  });

  it('неизвестный профиль показывается своим именем, а не пустотой', () => {
    expect(profileTitle('strict')).toBe('Строгий');
    expect(profileTitle('future_profile')).toBe('future_profile');
  });

  it('основной режим первым, новые неизвестные - в конце', () => {
    expect(orderProfiles(['shrubs', 'zzz', 'barriers', 'strict'])).toEqual([
      'strict',
      'barriers',
      'shrubs',
      'zzz',
    ]);
  });
});
