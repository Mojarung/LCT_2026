import { Link } from 'react-router';

import { useMeta } from '../../api/queries';

/** Штамп листа: название сервиса и на чём он стоит - числа свода норм и каталога видов. Как в
 *  угловом штампе чертежа, подпись графы мелко сверху, значение крупно под ней. */
export function ServiceFacts() {
  const meta = useMeta();
  const value = (n: number | undefined) => (n === undefined ? '-' : String(n));
  return (
    <header className="stamp">
      <div className="stamp-title">
        <h1>Озеленение улиц по DXF</h1>
        <p>Посадки на слоях GREEN_*, у каждой пункт нормы.</p>
      </div>
      <section className="stamp-facts" aria-labelledby="facts-title">
        <h2 className="visually-hidden" id="facts-title">
          Что применяется
        </h2>
        <dl className="facts">
          <div>
            <dt>правил в своде</dt>
            <dd>{value(meta.data?.rules.total)}</dd>
          </div>
          <div>
            <dt>основание сверено</dt>
            <dd>{value(meta.data?.rules.verified)}</dd>
          </div>
          <div>
            <dt>видов в каталоге</dt>
            <dd>
              {/* Число ведёт в базу моделей: чем каждый вид нарисован на плане. */}
              <Link to="/models" title="Модели растений на плане">
                {value(meta.data?.species.length)}
              </Link>
            </dd>
          </div>
          <div>
            <dt>акты</dt>
            <dd className="acts">СП 42.13330, 743-ПП, 623-ПП, 369-ПП</dd>
          </div>
        </dl>
      </section>
    </header>
  );
}
