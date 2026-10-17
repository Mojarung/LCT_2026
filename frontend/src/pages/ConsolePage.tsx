import type { ReactNode } from 'react';
import { Link } from 'react-router';

import { useMeta, useRuns, useStreets } from '../api/queries';
import { RecentRuns } from '../components/console/RecentRuns';
import { RunForm } from '../components/console/RunForm';
import { RECENT_LIMIT, RunsRegistry } from '../components/console/RunsRegistry';
import { InfoTip } from '../components/InfoTip';
import { UiIcon, type UiGlyph } from '../components/icons';
import { plural } from '../lib/format';

/** Шаги - действия человека и то, что в ответ делает сервис: по ним видно, зачем форма выше и
 *  что будет после кнопки. Значок вместо номера: порядок и так читается слева направо. */
function steps(species: number | undefined): { icon: UiGlyph; title: string; text: ReactNode }[] {
  return [
    {
      icon: 'upload',
      title: 'Выберите улицу',
      text: 'Улица пилотного проекта или свой чертёж DXF или DWG. Сети, опись деревьев и слои ГИС - по желанию.',
    },
    {
      icon: 'check',
      title: 'Сервис проверит нормы',
      text: 'Каждое место посадки - на отступы от сетей, зданий, бортов и опор по СП 42.13330, 743-ПП и 623-ПП.',
    },
    {
      icon: 'trees',
      title: 'Получите план',
      text: (
        <>
          Деревья и кустарник на слоях GREEN_* того же DXF, порода подобрана под место из{' '}
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
      icon: 'scene',
      title: 'Проверьте и поправьте',
      text: 'На карте видно, почему дерево стоит здесь и почему не встало там. Посадку можно перенести, улицу - посмотреть в 3D.',
    },
  ];
}

/** Главная - рабочий стол. Первый экран: что это за сервис, как выглядит его результат
 *  (фото улицы и план на слоях чертежа) и запуск. Ниже - реестр прогонов и как это работает. */
export function ConsolePage() {
  const meta = useMeta();
  const streets = useStreets();
  const runs = useRuns(RECENT_LIMIT);
  const noCatalog = (streets.isSuccess && streets.data.length === 0) || streets.isError;

  return (
    <div className="home">
      <section className="home-hero" aria-labelledby="hero-title">
        <div className="home-intro">
          <h1 id="hero-title">Озеленение улиц по нормам</h1>
          <p className="lead">
            Подоснова DXF или DWG на входе. На выходе - деревья и кустарник на слоях GREEN_* того же
            чертежа, и у каждой посадки пункт нормы, по которому она здесь стоит.
          </p>
          <a className="home-more" href="#how">
            Как это работает
          </a>
          {/* Результат сервиса - на первом экране: фото улицы после посадки и тот же план на
              слоях чертежа поверх подосновы и сетей. */}
          <figure className="home-collage">
            <span className="collage-stage">
              <span className="collage-frame">
                <img
                  className="collage-photo"
                  src="/landing/street.webp"
                  width={1600}
                  height={900}
                  alt="Улица после посадки: аллея вдоль дорожки, прохожие, новые дома"
                  fetchPriority="high"
                />
              </span>
              <span className="collage-plan">
                <img
                  src="/landing/plan.webp"
                  width={900}
                  height={428}
                  alt="Фрагмент плана: посадки на слоях GREEN_* поверх подосновы и сетей"
                />
                <span>План на слоях DXF</span>
              </span>
            </span>
            <figcaption>
              Фото нарисовано нейросетью по кадру 3D-вида плана. Это иллюстрация: нормы проверяются
              на чертеже.
            </figcaption>
          </figure>
        </div>
        <div className="home-side">
          <section className="panel home-start" id="launch" aria-labelledby="launch-title">
            <h2 className="panel-title" id="launch-title">
              Новый прогон
            </h2>
            <RunForm demo={noCatalog} />
          </section>
          <RecentRuns />
        </div>
      </section>

      <section className="panel home-runs" aria-labelledby="runs-title">
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

      <section className="home-how" id="how" aria-labelledby="steps-title">
        <h2 className="home-title" id="steps-title">
          Как это работает
        </h2>
        <ol className="how">
          {steps(meta.data?.species.length).map((step) => (
            <li key={step.title}>
              <UiIcon name={step.icon} size={22} />
              <b>{step.title}</b>
              <span>{step.text}</span>
            </li>
          ))}
        </ol>
      </section>
    </div>
  );
}
