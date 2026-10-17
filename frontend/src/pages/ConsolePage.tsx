import type { ReactNode } from 'react';
import { Link } from 'react-router';

import { useMeta, useRuns, useStreets } from '../api/queries';
import { RecentRuns } from '../components/console/RecentRuns';
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
      text: 'Улица пилотного проекта или свой чертёж DXF или DWG. Сети, опись деревьев и слои ГИС - по желанию.',
    },
    {
      title: 'Сервис проверит нормы',
      text: 'Каждое место посадки - на отступы от сетей, зданий, бортов и опор по СП 42.13330, 743-ПП и 623-ПП.',
    },
    {
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
          {/* Результат на первом экране: план прогона с выбранной посадкой и её отступами в
              метрах - то, ради чего сервис, - и фото той же улицы врезкой. Кадр плана снят с
              настоящего прогона (10004141, режим «Кроны»), фото - его же фото по 3D-кадру. */}
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
            <figcaption>
              Выноски - отступы выбранной посадки до борта и опоры в метрах против нормы. Фото
              нарисовано нейросетью по 3D-виду этого плана, это иллюстрация.
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
        <div className="how-body">
          <ol className="how">
            {steps(meta.data?.species.length).map((step) => (
              <li key={step.title}>
                <b>{step.title}</b>
                <span>{step.text}</span>
              </li>
            ))}
          </ol>
          {/* Ответ на «почему дерево здесь» - настоящая карточка посадки, снятая с прогона:
              замер, норма и пункт акта одним кликом по кроне. */}
          <figure className="how-card">
            <img
              src="/landing/planting-card.webp"
              width={678}
              height={813}
              alt="Карточка посадки № 151, сосна горная: допускается; ближе всего к норме - до силового кабеля 2,49 м при норме 2,00 м, СП 42.13330.2016, п. 9.6, табл. 9.1"
              loading="lazy"
            />
            <figcaption>Клик по кроне на плане открывает такую карточку.</figcaption>
          </figure>
        </div>
      </section>
    </div>
  );
}
