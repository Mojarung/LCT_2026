import { type ReactNode, useEffect, useState } from 'react';
import { Link } from 'react-router';

import { useMeta, useRuns, useStreets } from '../api/queries';
import { RunForm } from '../components/console/RunForm';
import { RECENT_LIMIT, RunsRegistry } from '../components/console/RunsRegistry';
import { InfoTip } from '../components/InfoTip';
import { plural } from '../lib/format';

/** Шаги - действия человека и то, что в ответ делает сервис: по ним видно, зачем форма выше и
 *  что будет после кнопки. Порядок - настоящий список, без номеров и значков. */
function steps(species: number | undefined): { title: string; text: ReactNode }[] {
  return [
    {
      title: 'Выберите улицу',
      text: 'Улица пилота или свой DXF/DWG; сети, опись и слои ГИС - по желанию.',
    },
    {
      title: 'Сервис проверит нормы',
      text: 'Отступы от сетей, зданий, бортов и опор по СП 42.13330, 743-ПП и 623-ПП.',
    },
    {
      title: 'Получите план',
      text: (
        <>
          Деревья и кустарник на слоях GREEN_*, порода из{' '}
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
      text: 'Клик по кроне - норма и метры; посадку можно перенести, улицу - открыть в 3D.',
    },
  ];
}

/** Первый заход на главную за сессию браузера: вступление играет один раз, дальше страница
 *  просто проявляется - смотреть одно и то же при каждом возврате из прогона утомляет. */
const INTRO_KEY = 'green-home-intro';

function useFirstVisit(): boolean {
  const [first] = useState(() => {
    try {
      return !sessionStorage.getItem(INTRO_KEY);
    } catch {
      return false;
    }
  });
  useEffect(() => {
    try {
      sessionStorage.setItem(INTRO_KEY, '1');
    } catch {
      /* без хранилища вступление просто сыграет снова */
    }
  }, []);
  return first;
}

/** Главная - рабочий стол. Первый экран: что это за сервис, как выглядит его результат
 *  (фото улицы и план на слоях чертежа) и запуск. Ниже - реестр прогонов и как это работает. */
export function ConsolePage() {
  const meta = useMeta();
  const streets = useStreets();
  const runs = useRuns(RECENT_LIMIT);
  const noCatalog = (streets.isSuccess && streets.data.length === 0) || streets.isError;
  const intro = useFirstVisit();

  // Главная - один экран: подвал с логотипом уходил бы за сгиб и заставлял листать.
  useEffect(() => {
    document.body.classList.add('shell-home');
    return () => {
      document.body.classList.remove('shell-home');
    };
  }, []);

  return (
    <div className="home" data-intro={intro ? 'play' : undefined}>
      {/* Один экран без прокрутки: слева что это и как выглядит результат, под ним - как это
          работает; справа запуск и реестр прогонов, реестр прокручивается внутри себя. */}
      <section className="home-hero" aria-labelledby="hero-title">
        {/* Лист со знака сервиса - слева от заголовка, высотой в обе строки. Строки заголовка -
            в масках: на вступлении лист вырастает от черенка, затем строки выезжают снизу. */}
        <div className="hero-title">
          <img className="hero-leaf" src="/leaf.webp" width={156} height={280} alt="" />
          <h1 id="hero-title">
            <span className="h1-line">
              <span>Озеленение</span>
            </span>{' '}
            <span className="h1-line">
              <span>улиц по нормам</span>
            </span>
          </h1>
        </div>
        <p className="lead">
          Подоснова DXF или DWG на входе. На выходе - деревья и кустарник на слоях GREEN_* того же
          чертежа, и у каждой посадки пункт нормы, по которому она здесь стоит.
        </p>
        {/* Кадр плана снят с настоящего прогона (10004141, режим «Кроны»): выбранная посадка и
            её отступы в метрах; фото - того же прогона по 3D-кадру. */}
        <figure className="home-collage">
          <span className="collage-stage">
            <span className="collage-frame">
              <img
                className="collage-main"
                src="/landing/plan-callout.webp"
                width={1760}
                height={1100}
                alt="План посадок на подоснове: у выбранной посадки выноски «борт 2,00 ≥ 2,00» и «опора 7,33 ≥ 4,00»"
                fetchPriority="high"
              />
            </span>
            <span className="collage-inset">
              <img
                src="/landing/street-photo.webp"
                width={1280}
                height={720}
                alt="Фото той же улицы по кадру 3D-вида: газон с гранитным бортом, кустарник, деревья вдоль дороги"
                loading="lazy"
              />
              <span>Фото по 3D-кадру</span>
            </span>
          </span>
          <figcaption>Фото нарисовано нейросетью по 3D-кадру этого плана.</figcaption>
        </figure>
        <section className="home-how" id="how" aria-labelledby="steps-title">
          <h2 className="visually-hidden" id="steps-title">
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
      </section>

      <div className="home-side">
        <section className="panel home-start" id="launch" aria-labelledby="launch-title">
          <h2 className="panel-title" id="launch-title">
            Новый прогон
          </h2>
          <RunForm demo={noCatalog} />
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
      </div>
    </div>
  );
}
