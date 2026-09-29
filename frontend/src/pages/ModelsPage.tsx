import { Link } from 'react-router';

import { useMeta } from '../api/queries';
import { ModelSwatch } from '../components/run/ModelSwatch';
import { ALL_MODELS, EXISTING_SHRUB, EXISTING_TREE, type Form } from '../map/models';

const GROUPS: { id: string; title: string; forms: readonly Form[] }[] = [
  {
    id: 'broadleaf',
    title: 'Лиственные деревья',
    forms: ['broadleaf', 'rounded', 'columnar', 'weeping'],
  },
  { id: 'conifer', title: 'Хвойные', forms: ['conifer', 'dwarf_conifer', 'creeper'] },
  { id: 'shrub', title: 'Кустарники', forms: ['shrub'] },
];

const FORM_RU: Record<Form, string> = {
  broadleaf: 'крупное лиственное',
  rounded: 'малое лиственное',
  columnar: 'колонновидное',
  weeping: 'плакучее',
  conifer: 'хвойное дерево',
  dwarf_conifer: 'низкое хвойное',
  shrub: 'кустарник',
  creeper: 'стелющееся хвойное',
};

const metres = (value: number) => value.toFixed(1).replace('.', ',');

/** База моделей: чем каждый вид каталога нарисован на плане. Тот же спрайт, что на карте,
 *  поэтому страница - это и легенда, и проверка, что у каждого вида своя модель. */
export function ModelsPage() {
  const meta = useMeta();
  const species = new Map((meta.data?.species ?? []).map((s) => [s.code, s]));
  return (
    <div className="launch">
      <div className="sheet">
        <header className="stamp">
          <div className="stamp-title">
            <h1>Модели растений</h1>
            <p>
              Чем каждый вид каталога нарисован на плане: форма кроны, листва, цветение и плоды.
            </p>
          </div>
          <p className="models-back">
            <Link to="/">← все прогоны</Link>
          </p>
        </header>
        <div className="models-body">
          {GROUPS.map((group) => {
            const models = ALL_MODELS.filter((model) => group.forms.includes(model.form));
            return (
              <section key={group.id} aria-labelledby={`models-${group.id}`}>
                <h2 className="section-label" id={`models-${group.id}`}>
                  {group.title}: {models.length}
                </h2>
                <ul className="models-grid">
                  {models.map((model) => {
                    const known = species.get(model.code);
                    return (
                      <li key={model.code}>
                        <ModelSwatch
                          model={model}
                          modelKey={model.code}
                          size={60}
                          style="illustrated"
                        />
                        <div>
                          <b>{model.name}</b>
                          {known ? <i>{known.name_lat}</i> : null}
                          <span>
                            {FORM_RU[model.form]}
                            {known ? <>, крона {metres(known.crown_diameter_m)}&nbsp;м</> : null}
                          </span>
                        </div>
                      </li>
                    );
                  })}
                </ul>
              </section>
            );
          })}
          <section aria-labelledby="models-existing">
            <h2 className="section-label" id="models-existing">
              Существующие насаждения
            </h2>
            <ul className="models-grid">
              <li>
                <ModelSwatch
                  model={EXISTING_TREE}
                  modelKey="~existing-tree"
                  look="existing"
                  size={60}
                  style="illustrated"
                />
                <div>
                  <b>Дерево по съёмке</b>
                  <span>знак или кружок кроны с подосновы, вид неизвестен</span>
                </div>
              </li>
              <li>
                <ModelSwatch
                  model={EXISTING_SHRUB}
                  modelKey="~existing-shrub"
                  look="existing"
                  size={60}
                  style="illustrated"
                />
                <div>
                  <b>Кустарник по съёмке</b>
                  <span>бледная крона с крестиком, не из плана</span>
                </div>
              </li>
            </ul>
          </section>
        </div>
      </div>
    </div>
  );
}
