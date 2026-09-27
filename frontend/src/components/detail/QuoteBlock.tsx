import type { Rule } from '../../api/artifacts';
import { listQuote, quoteOf, tableQuote } from '../../lib/quotes';

/** Цитата нормы под проверкой: перечень - списком, строка табл. 9.1 - колонками «до ствола
 *  дерева» и «до кустарника», остальное - текстом, как в акте. */
export function QuoteBlock({ rule }: { rule: Rule | undefined }) {
  if (!rule) return null;
  const text = quoteOf(rule);
  if (!text) return null;
  const pairs = listQuote(text);
  if (pairs) {
    return (
      <div className="check-quote">
        <ul className="quote-rows">
          {pairs.map((pair) => (
            <li key={pair.what}>
              <span>{pair.what}</span>
              <b>{pair.value}</b>
            </li>
          ))}
        </ul>
      </div>
    );
  }
  const table = tableQuote(text);
  if (!table) return <p className="check-quote">{text}</p>;
  return (
    <div className="check-quote">
      {table.what}
      <p className="quote-cols">
        <span>
          до ствола дерева <b>{table.tree}</b>
        </span>
        <span>
          до кустарника <b>{table.shrub}</b>
        </span>
      </p>
      {table.note ? <p className="quote-note">{table.note}</p> : null}
    </div>
  );
}
