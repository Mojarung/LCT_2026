import { describe, expect, it } from 'vitest';

/* Карта берёт цвета из CSS-переменных, и опечатку в имени переменной ничто не ловит: палитра
 * подставляет запасной серый, поэтому несуществующий токен даёт не отказ, а тихую деградацию.
 * Так отметка выбранной посадки однажды рисовалась служебным серым и на общем виде пропадала,
 * при чистой консоли и нормальном скриншоте. */

const sources = import.meta.glob<string>(['/src/**/*.{ts,tsx}', '!/src/**/*.test.{ts,tsx}'], {
  query: '?raw',
  import: 'default',
  eager: true,
});
const styles = import.meta.glob<string>('/src/styles/*.css', {
  query: '?raw',
  import: 'default',
  eager: true,
});

/** Имя переменной в кавычках ('--c-water') или внутри var(...). */
const USED = /['"(](--[a-z][a-z0-9-]*)/g;
const DECLARED = /^\s*(--[a-z][a-z0-9-]*)\s*:/gm;
/** Переменные, которые код ставит сам: setProperty('--legend-h') или ключ inline-стиля
 *  ['--share']. Объявлять их в стилях не нужно. */
const SET_BY_CODE = /(?:setProperty\(\s*|\[\s*)['"](--[a-z][a-z0-9-]*)['"]/g;

const names = (text: string, pattern: RegExp): Set<string> =>
  new Set([...text.matchAll(pattern)].map((match) => match[1] ?? ''));

describe('CSS-переменные', () => {
  it('каждая переменная, которую читает код, объявлена в стилях', () => {
    const code = Object.values(sources).join('\n');
    const css = Object.values(styles).join('\n');
    const used = names(code, USED);
    const declared = names(css, DECLARED);
    const setByCode = names(code, SET_BY_CODE);

    // Разбор жив: карта одна читает два десятка цветов.
    expect(used.size).toBeGreaterThan(20);
    expect(declared.size).toBeGreaterThan(20);
    const missing = [...used].filter((name) => !declared.has(name) && !setByCode.has(name));
    expect(missing.sort()).toEqual([]);
  });

  it('проверка заметила бы опечатку', () => {
    const used = names("stroke: '--c-watr', fill: 'var(--ok)'", USED);
    const declared = names('  --c-water: #09f;\n  --ok: #0a0;\n', DECLARED);

    expect([...used].filter((name) => !declared.has(name))).toEqual(['--c-watr']);
  });
});
