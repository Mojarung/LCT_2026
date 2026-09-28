import { describe, expect, it } from 'vitest';

import { runnersText } from './alternatives';

describe('runnersText', () => {
  it('says a shared reason once for the runners-up that lost to it', () => {
    const quota = 'квота вида 10% исчерпана';
    expect(
      runnersText([
        { code: 'crataegus', name_ru: 'Боярышник', percent: 74, why_not: quota },
        { code: 'ulmus', name_ru: 'Вяз', percent: 72, why_not: quota },
        { code: 'acer', name_ru: 'Клён', percent: 60, why_not: 'оценка ниже' },
      ]),
    ).toBe('Боярышник 74%, Вяз 72%: квота вида 10% исчерпана; Клён 60%');
  });
});
