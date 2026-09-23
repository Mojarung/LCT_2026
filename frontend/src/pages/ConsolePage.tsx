import { useStreets } from '../api/queries';
import { DemoStart } from '../components/console/DemoStart';
import { RunForm } from '../components/console/RunForm';
import { RunsRegistry } from '../components/console/RunsRegistry';
import { ServiceFacts } from '../components/console/ServiceFacts';

/** Консоль, а не лендинг: два модуля из тех же поверхностей, что парят над планом на странице
 *  прогона, - «запустить» и «что уже посчитано». */
export function ConsolePage() {
  const streets = useStreets();
  const noCatalog = streets.isSuccess && streets.data.length === 0;

  return (
    <div className="launch">
      <div className="launch-inner">
        <section className="panel" aria-labelledby="launch-title">
          <h1 className="visually-hidden" id="launch-title">
            Новый прогон
          </h1>
          {noCatalog || streets.isError ? <DemoStart /> : null}
          <RunForm />
        </section>

        <section className="panel" aria-labelledby="runs-title">
          <h2 className="section-label" id="runs-title">
            Прогоны
          </h2>
          <RunsRegistry />
          <ServiceFacts />
        </section>
      </div>
    </div>
  );
}
