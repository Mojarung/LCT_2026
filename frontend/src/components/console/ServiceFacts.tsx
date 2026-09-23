import { useMeta } from '../../api/queries';

/** Что применяет сервис: числа свода норм и каталога. Числа крупно, подписи мелко - как число
 *  посадок на рабочем месте: «числа важнее слов» на обеих страницах одинаково. */
export function ServiceFacts() {
  const meta = useMeta();
  const value = (n: number | undefined) => (n === undefined ? '-' : String(n));
  return (
    <section aria-labelledby="facts-title">
      <h2 className="section-label section-gap" id="facts-title">
        Что применяется
      </h2>
      <dl className="facts">
        <div>
          <dt>правил в своде</dt>
          <dd>{value(meta.data?.rules.total)}</dd>
        </div>
        <div>
          <dt>из них с проверенным основанием</dt>
          <dd>{value(meta.data?.rules.verified)}</dd>
        </div>
        <div>
          <dt>видов в каталоге</dt>
          <dd>{value(meta.data?.species.length)}</dd>
        </div>
        <div>
          <dt>акты</dt>
          <dd className="acts">СП 42.13330, 743-ПП, 623-ПП, 369-ПП</dd>
        </div>
      </dl>
    </section>
  );
}
