import type { ReactNode } from 'react';
import { Link } from 'react-router';

import { useMeta, useRuns, useStreets } from '../api/queries';
import { InfoTip } from '../components/InfoTip';
import { RunForm } from '../components/console/RunForm';
import { RECENT_LIMIT, RunsRegistry } from '../components/console/RunsRegistry';
import { plural } from '../lib/format';

/** Шаги - действия человека и то, что в ответ делает сервис: по ним видно, зачем форма ниже
 *  и что будет после кнопки. */
function steps(species: number | undefined): { title: string; text: ReactNode }[] {
  return [
    {
      title: 'Выберите улицу',
      text: 'Улица пилотного проекта или свой чертёж DXF или DWG. Сети, опись деревьев и слои ГИС добавляются по желанию.',
    },
    {
      title: 'Сервис проверит нормы',
      text: 'Каждое место посадки проверяется на отступы от сетей, зданий, бортов и опор по СП 42.13330, 743-ПП и 623-ПП.',
    },
    {
      title: 'Получите план',
      text: (
        <>
          Деревья и кустарник на слоях GREEN_* того же DXF. Порода подобрана под место из{' '}
          <Link to="/models">
            каталога
            {species
              ? ` ${String(species)} ${plural(species, 'вида', 'видов', 'видов')}`
              : ' видов'}
          </Link>
          .
        </>
      ),
    },
    {
      title: 'Проверьте и поправьте',
      text: 'На карте видно, почему дерево стоит здесь и почему не встало там. Посадку можно перенести, план пересобрать, улицу посмотреть в 3D.',
    },
  ];
}

/** Главная: что делает сервис, как им пользоваться, затем запуск и реестр прогонов. */
export function ConsolePage() {
  const meta = useMeta();
  const streets = useStreets();
  const runs = useRuns(RECENT_LIMIT);
  const noCatalog = (streets.isSuccess && streets.data.length === 0) || streets.isError;

  return (
    <div className="landing">
      <section className="hero" aria-labelledby="hero-title">
        <div className="hero-copy">
          <h1 id="hero-title">Озеленение улицы по нормам и подземным сетям</h1>
          <p className="lead">
            Загрузите чертёж подосновы: сервис расставит деревья и кустарник с отступами от сетей,
            запишет план на отдельные слои DXF и объяснит каждую посадку пунктом нормы.
          </p>
          <p className="hero-links">
            <a href="#launch" className="primary">
              Запустить прогон
            </a>
            <a href="#how">Как это работает</a>
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

      <section className="steps-strip" id="how" aria-labelledby="steps-title">
        <h2 className="landing-title" id="steps-title">
          Как это работает
        </h2>
        <ol className="how">
          {steps(meta.data?.species.length).map((step) => (
            <li key={step.title}>
              <b>{step.title}</b>
              <span>{step.text}</span>
            </li>
          ))}
        </ol>
      </section>

      <div className="workbench">
        <section className="panel launch-panel" id="launch" aria-labelledby="launch-title">
          <h2 className="panel-title" id="launch-title">
            Новый прогон
          </h2>
          <RunForm demo={noCatalog} />
        </section>
        <section className="panel runs-panel" aria-labelledby="runs-title">
          <div className="runs-head">
            <h2 className="panel-title" id="runs-title">
              Прогоны
              {runs.data?.length ? <span className="count">{runs.data.length}</span> : null}
            </h2>
            <InfoTip term="Прогоны">
              Прогон - один расчёт улицы с выбранными параметрами. Внутри план на карте, объяснение
              каждой посадки, 3D-вид и выгрузка DXF.
            </InfoTip>
          </div>
          <RunsRegistry />
        </section>
      </div>
    </div>
  );
}
