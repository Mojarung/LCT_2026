import { Link } from 'react-router';

import { useMeta, useRuns, useStreets } from '../api/queries';
import { RunForm } from '../components/console/RunForm';
import { RECENT_LIMIT, RunsRegistry } from '../components/console/RunsRegistry';

const STEPS = [
  {
    title: 'Чертёж',
    text: 'DXF подосновы Мосгеотреста с сетями. Комплект чертежей, перечётная ведомость и слои ГИС - по желанию.',
  },
  {
    title: 'Нормы',
    text: 'Каждая яма проверяется на отступы от сетей, зданий, бортов и опор: СП 42.13330, 743-ПП, 623-ПП.',
  },
  {
    title: 'План',
    text: 'Аллеи вдоль бортов, группы на газоне, ряды и изгороди кустарника, газоны. Вид подбирается под место.',
  },
  {
    title: 'Выгрузка',
    text: 'DXF с планом на слоях GREEN_*, объяснение каждой посадки с пунктом акта, 3D-вид и фото улицы.',
  },
] as const;

/** Главная: что делает сервис и как им пользоваться - на первом экране, запуск и реестр прогонов
 *  сразу под ним. Числа свода и каталога - из /api/v1/meta, а не из текста страницы. */
export function ConsolePage() {
  const meta = useMeta();
  const streets = useStreets();
  const runs = useRuns(RECENT_LIMIT);
  const noCatalog = (streets.isSuccess && streets.data.length === 0) || streets.isError;
  const value = (n: number | undefined) => (n === undefined ? '-' : String(n));

  return (
    <div className="landing">
      <section className="hero" aria-labelledby="hero-title">
        <div className="hero-copy">
          <p className="eyebrow">green · ЛЦТ 2026, кейс ДПиООС</p>
          <h1 id="hero-title">Озеленение улицы по нормам и подземным сетям</h1>
          <p className="lead">
            Загрузите чертёж подосновы: сервис расставит деревья и кустарник с отступами от сетей,
            запишет план на отдельные слои DXF и объяснит каждую посадку пунктом нормы.
          </p>
          <dl className="hero-facts" role="region" aria-label="Нормы и каталог видов">
            <div>
              <dt>правил в своде норм</dt>
              <dd>{value(meta.data?.rules.total)}</dd>
            </div>
            <div>
              <dt>видов в каталоге</dt>
              <dd>
                <Link to="/models" title="Как каждый вид нарисован на плане">
                  {value(meta.data?.species.length)}
                </Link>
              </dd>
            </div>
            <div>
              <dt>исходных объектов меняется</dt>
              <dd>0</dd>
            </div>
          </dl>
          <p className="hero-links">
            <a href="#launch" className="primary">
              Запустить прогон
            </a>
            <a href="/docs" target="_blank" rel="noopener">
              HTTP API и Swagger ↗
            </a>
            <Link to="/models">Модели растений</Link>
          </p>
        </div>
        <figure className="hero-visual">
          <img
            className="hero-photo"
            src="/landing/street.webp"
            width={1600}
            height={900}
            alt="Улица после посадки: аллея вдоль дорожки, прохожие, новые дома"
            fetchPriority="high"
          />
          <div className="hero-plan">
            <img
              src="/landing/plan.webp"
              width={900}
              height={428}
              alt="Фрагмент плана: посадки на слоях GREEN_* поверх подосновы и сетей"
              loading="lazy"
            />
            <span>план на слоях GREEN_*</span>
          </div>
          <figcaption>
            Фото нарисовано нейросетью по кадру 3D-вида того же плана: иллюстрация, нормы
            проверяются на чертеже.
          </figcaption>
        </figure>
      </section>

      <div className="workbench">
        <section className="panel launch-panel" id="launch" aria-labelledby="launch-title">
          <h2 className="panel-title" id="launch-title">
            Новый прогон
          </h2>
          <RunForm demo={noCatalog} />
        </section>
        <section className="panel runs-panel" aria-labelledby="runs-title">
          <h2 className="panel-title" id="runs-title">
            Прогоны
            {runs.data?.length ? <span className="count">{runs.data.length}</span> : null}
          </h2>
          <RunsRegistry />
        </section>
      </div>

      <section className="steps-strip" aria-labelledby="steps-title">
        <h2 className="panel-title" id="steps-title">
          Как это работает
        </h2>
        <ol className="how">
          {STEPS.map((step) => (
            <li key={step.title}>
              <b>{step.title}</b>
              <span>{step.text}</span>
            </li>
          ))}
        </ol>
      </section>
    </div>
  );
}
