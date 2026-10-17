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

/** Главная - рабочий стол: короткая строка о сервисе, сразу под ней запуск и реестр
 *  прогонов, ниже - как это работает и пример результата. Раньше первый экран занимала
 *  обложка, и до формы запуска приходилось листать. */
export function ConsolePage() {
  const meta = useMeta();
  const streets = useStreets();
  const runs = useRuns(RECENT_LIMIT);
  const noCatalog = (streets.isSuccess && streets.data.length === 0) || streets.isError;

  return (
    <div className="landing">
      <header className="console-head" aria-labelledby="hero-title">
        <div>
          <h1 id="hero-title">Озеленение улиц по нормам</h1>
          <p className="lead">
            Загрузите подоснову DXF или DWG: сервис расставит деревья и кустарник с отступами от
            сетей, запишет план на слои GREEN_* того же чертежа и объяснит каждую посадку пунктом
            нормы.
          </p>
          <nav className="console-links" aria-label="Справка">
            <a href="#how">Как это работает</a>
            <Link to="/models">Модели растений</Link>
          </nav>
        </div>
        <figure className="console-shots">
          <img
            src="/landing/plan.webp"
            width={277}
            height={132}
            alt="Фрагмент плана: посадки на слоях GREEN_* поверх подосновы и сетей"
          />
          <img
            src="/landing/street.webp"
            width={235}
            height={132}
            alt="Фото по кадру 3D-вида того же плана"
          />
          <figcaption>План на слоях DXF и фото по 3D-кадру</figcaption>
        </figure>
      </header>

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

      <section className="how-section" id="how" aria-labelledby="steps-title">
        <div>
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
        </div>
        <figure className="how-visual">
          <img
            src="/landing/street.webp"
            width={1600}
            height={900}
            alt="Улица после посадки: аллея вдоль дорожки, прохожие, новые дома"
            loading="lazy"
          />
          <figcaption>
            Фото нарисовано нейросетью по кадру 3D-вида плана. Это иллюстрация: нормы проверяются на
            чертеже.
          </figcaption>
        </figure>
      </section>
    </div>
  );
}
