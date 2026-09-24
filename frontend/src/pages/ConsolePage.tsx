import { useStreets } from '../api/queries';
import { RunForm } from '../components/console/RunForm';
import { RunsRegistry } from '../components/console/RunsRegistry';
import { ServiceFacts } from '../components/console/ServiceFacts';

/** Консоль, а не лендинг: лист чертежа со штампом сверху - что это за сервис и на каком своде
 *  норм он работает, - и две графы под ним: «запустить» и «что уже посчитано». */
export function ConsolePage() {
  const streets = useStreets();
  const noCatalog = (streets.isSuccess && streets.data.length === 0) || streets.isError;

  return (
    <div className="launch">
      <div className="sheet">
        <ServiceFacts />
        <div className="sheet-body">
          <section className="sheet-cell" aria-labelledby="launch-title">
            <h2 className="section-label" id="launch-title">
              Новый прогон
            </h2>
            <RunForm demo={noCatalog} />
          </section>
          <section className="sheet-cell" aria-labelledby="runs-title">
            <h2 className="section-label" id="runs-title">
              Прогоны
            </h2>
            <RunsRegistry />
          </section>
        </div>
      </div>
    </div>
  );
}
