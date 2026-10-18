import { integer } from '../../lib/format';
import { isShrubType, modelKey, modelOf } from '../../map/models';
import type { MapItem } from '../../map/types';
import { useEngine } from '../../state/engine';
import { useWorkspace } from '../../state/workspace';
import { ModelSwatch } from '../run/ModelSwatch';

interface Row {
  code: string;
  name: string;
  count: number;
  plantingType: string;
}

function rowsOf(placements: readonly MapItem[]): Row[] {
  const byCode = new Map<string, Row>();
  for (const item of placements) {
    const code = item.species_code ?? '';
    const row = byCode.get(code) ?? {
      code,
      name: item.species_ru || 'вид не назначен',
      count: 0,
      plantingType: item.planting_type,
    };
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
  const engine = useEngine();

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
  // Полоса меряется самым частым видом группы, а не суммой: при тринадцати видах доли от
  // суммы укладываются в 10%, и все полосы выглядят одинаково короткими.
  const groups = [
    { title: 'Деревья', rows: rows.filter((row) => !isShrubType(row.plantingType)) },
    { title: 'Кустарники', rows: rows.filter((row) => isShrubType(row.plantingType)) },
  ]
    .filter((group) => group.rows.length)
    .map((group) => ({
      ...group,
      count: group.rows.reduce((sum, row) => sum + row.count, 0),
      top: group.rows[0]?.count ?? 1,
    }));
  return (
    <>
      {/* Число посадок крупно стоит в сводке слева, список подписан вкладкой «Посадки»:
          заголовок - только для читалки экрана и навигации по заголовкам. */}
      <h2 className="visually-hidden">Состав плана: {integer(total)}</h2>
      {visible === total ? null : (
        <p className="detail-note">
          Показано {integer(visible)} из {integer(total)}.{' '}
          <button type="button" className="linkish" onClick={showAll}>
            показать все
          </button>
        </p>
      )}
      {/* Деревья и кустарники - отдельными группами со своим числом: «сколько деревьев» -
          первый вопрос заказчика, и ответ на него теперь здесь, а не плитками слева. */}
      {groups.map((group) => (
        <section className="composition-group" key={group.title} aria-label={group.title}>
          <h3 className="composition-group-title">
            {group.title}
            <span className="count">{integer(group.count)}</span>
          </h3>
          <ul className="composition">
            {group.rows.map((row, index) => {
              const off = speciesOff.has(row.code);
              return (
                <li
                  key={row.code}
                  className={off ? 'off' : ''}
                  style={{ ['--i' as string]: String(Math.min(index, 12)) }}
                >
                  <input
                    type="checkbox"
                    className="composition-see"
                    title="Показывать вид на карте"
                    checked={!off}
                    aria-label={`Показывать на карте: ${row.name}`}
                    onChange={(event) => {
                      toggleSpecies(row.code, event.target.checked);
                    }}
                  />
                  <button
                    type="button"
                    aria-pressed={highlight === row.code}
                    title="Подсветить вид на карте"
                    onClick={() => {
                      if (highlight !== row.code) engine.current?.showSpecies(row.code);
                      toggleHighlight(row.code);
                    }}
                  >
                    <span
                      className="composition-bar"
                      style={{
                        ['--share' as string]: `${((row.count / group.top) * 100).toFixed(1)}%`,
                      }}
                    />
                    {/* Образец модели - то, чем вид нарисован на карте: состав плана он же и
                      легенда видов. */}
                    <ModelSwatch
                      model={modelOf(row.code, row.plantingType)}
                      modelKey={modelKey(row.code, row.plantingType)}
                      shrub={isShrubType(row.plantingType)}
                      size={22}
                    />
                    <span className="composition-name">{row.name}</span>
                    <span className="composition-count">{integer(row.count)}</span>
                  </button>
                </li>
              );
            })}
          </ul>
        </section>
      ))}
    </>
  );
}
