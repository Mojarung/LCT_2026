// Золотой файл разбора цитат норм: вход - все правила rules.json настоящего прогона, выход -
// то, что с ними делали функции старого static/plan.js. Новая реализация на TypeScript
// обязана совпасть с ним везде, кроме осознанных правок, отмеченных в тесте.
//
// Запуск: node scripts/golden-quotes.mjs <plan.js> <rules.json> <out.json>
import { readFileSync, writeFileSync } from 'node:fs';

const [planPath, rulesPath, outPath] = process.argv.slice(2);
const source = readFileSync(planPath, 'utf8');

/** Текст функции name из исходника: от «function name(» до парной закрывающей скобки. */
function cut(name) {
  const start = source.indexOf(`function ${name}(`);
  if (start < 0) throw new Error(`нет функции ${name}`);
  let depth = 0;
  for (let i = source.indexOf('{', start); i < source.length; i += 1) {
    if (source[i] === '{') depth += 1;
    if (source[i] === '}' && --depth === 0) return source.slice(start, i + 1);
  }
  throw new Error(`не закрыта функция ${name}`);
}

const names = ['clauseNumber', 'quoteOf', 'tableQuote', 'listQuote'];
const factory = new Function(`${names.map(cut).join('\n')}\nreturn { ${names.join(', ')} };`);
const fns = factory();

const rules = JSON.parse(readFileSync(rulesPath, 'utf8')).rules;
const cases = Object.values(rules).map((rule) => {
  const text = fns.quoteOf(rule);
  return {
    rule_id: rule.rule_id,
    clause: rule.clause,
    quote: rule.quote,
    clauseNumber: fns.clauseNumber(rule),
    quoteOf: text,
    table: text ? fns.tableQuote(text) : null,
    list: text ? fns.listQuote(text) : null,
  };
});
writeFileSync(outPath, `${JSON.stringify(cases, null, 1)}\n`);
console.log(
  `правил: ${cases.length}, таблиц: ${cases.filter((c) => c.table).length}, перечней: ${cases.filter((c) => c.list).length}`,
);
