import { integer } from '../../lib/format';
import type { MapItem } from '../../map/types';
import { useWorkspace } from '../../state/workspace';

interface Row {
  code: string;
  name: string;
  count: number;
}

function rowsOf(placements: readonly MapItem[]): Row[] {
  const byCode = new Map<string, Row>();
  for (const item of placements) {
    const code = item.species_code ?? '';
    const row = byCode.get(code) ?? { code, name: item.species_ru || 'вид не назначен', count: 0 };
    row.count += 1;
    byCode.set(code, row);
  }
  return [...byCode.values()].sort((a, b) => b.count - a.count);
}

/** Состав плана: строка вида - кнопка, она подсвечивает свой вид на карте; галочка оставляет
 *  вид на карте или прячет его. Тринадцать видов в одном кадре сливаются, и вопрос «где именно
 *  липы» иначе не задать. */
export function Composition({ placements }: { placements: readonly MapItem[] }) {
  const speciesOff = useWorkspace((s) => s.speciesOff);
  const highlight = useWorkspace((s) => s.highlight);
  const toggleSpecies = useWorkspace((s) => s.toggleSpecies);
  const showAll = useWorkspace((s) => s.showAllSpecies);
  const toggleHighlight = useWorkspace((s) => s.toggleHighlight);

  const rows = rowsOf(placements);
  if (!rows.length) {
    return (
      <div className="detail-empty">
        <p>В этом прогоне посадок нет.</p>
      </div>
    );
  }
  const total = placements.length;
  const visible = placements.filter((p) => !speciesOff.has(p.species_code ?? '')).length;
  // Полоса меряется самым частым видом, а не суммой: при тринадцати видах доли от суммы
  // укладываются в 10%, и все полосы выглядят одинаково короткими.
  const top = rows[0]?.count ?? 1;
  return (
    <>
      <h2 className="detail-heading">Состав плана: {integer(total)}</h2>
      <p className="detail-note">
        Галочка оставляет вид на карте, клик по строке подсвечивает его.
        {visible === total ? null : (
          <>
            {' '}
            Показано {integer(visible)} из {integer(total)}.{' '}
            <button type="button" className="linkish" onClick={showAll}>
              показать все
            </button>
          </>
        )}
      </p>
      <ul className="composition">
        {rows.map((row) => {
          const off = speciesOff.has(row.code);
          return (
            <li key={row.code} className={off ? 'off' : ''}>
              <input
                type="checkbox"
                className="composition-see"
                checked={!off}
                aria-label={`Показывать на карте: ${row.name}`}
                onChange={(event) => {
                  toggleSpecies(row.code, event.target.checked);
                }}
              />
              <button
                type="button"
                aria-pressed={highlight === row.code}
                onClick={() => {
                  toggleHighlight(row.code);
                }}
              >
                <span
                  className="composition-bar"
                  style={{ ['--share' as string]: `${((row.count / top) * 100).toFixed(1)}%` }}
                />
                <span className="composition-name">{row.name}</span>
                <span className="composition-count">{integer(row.count)}</span>
              </button>
            </li>
          );
        })}
      </ul>
      <p className="detail-empty" style={{ marginTop: 14 }}>
        Клик по посадке на карте покажет норму, по которой она стоит.
      </p>
    </>
  );
}
