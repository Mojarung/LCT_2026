import { useId, useRef, useState, type ReactNode, type SyntheticEvent } from 'react';
import { useNavigate } from 'react-router';

import { postForm } from '../../api/client';
import { useMeta, useProfile, useStreets } from '../../api/queries';
import type { RunOut } from '../../api/types';
import { plain } from '../../lib/format';
import {
  diffOverrides,
  formDefaults,
  parseAdvanced,
  type RunFormValues,
  type Switch,
} from '../../lib/overrides';
import { orderProfiles, PROFILES, profileTitle } from '../../lib/profiles';
import { InfoTip } from '../InfoTip';
import { useDemoStart } from './DemoStart';
import { FileField } from './FileField';

/** Приёмы по порядку работы конвейера: деревья, потом кустарник от борта к газону. Две строки
 *  про группы кустарника различаются тем, откуда место: пустое после квот деревьев или
 *  свободный газон. Определение каждого приёма - в окошке рядом с подписью, основания - из
 *  приложения D документации. */
const SWITCHES: { name: Switch | 'fill'; label: string; info: string }[] = [
  {
    name: 'fill',
    label: 'Добор узких полос и карманов газона',
    info: 'После аллеи вдоль борта и сетки на газоне сервис ищет узкие полосы и карманы, куда сетка не легла, и ставит туда деревья, если все отступы соблюдены.',
  },
  {
    name: 'shrub_rows',
    label: 'Ряд кустарника у борта под кронами аллеи',
    info: 'Нижний ярус под деревьями аллеи вдоль борта: задерживает пыль и соль с проезжей части.',
  },
  {
    name: 'curb_hedges',
    label: 'Живая изгородь вдоль остальных бортов, до 720 кустов на 1 км',
    info: 'Изгородь вдоль бортов с грунтом, где нет аллеи (СП 82.13330, п. 9.38). Не больше 720 кустов на 1 км улицы.',
  },
  {
    name: 'understory',
    label: 'Кустарник под кроной дерева, где ряда нет',
    info: 'Небольшая группа кустарника под деревом без нижнего яруса (МГСН 1.02-02, п. 4.2.9.2). Даёт ярусность там, где ряда у борта нет.',
  },
  {
    name: 'shrub_groups',
    label: 'Кустарник там, где квоты не пустили дерево',
    info: 'Место прошло все нормы, но породы для дерева не нашлось из-за квот разнообразия: доля одной породы в посадках ограничена. Чтобы место не пустовало, туда сажается группа кустарника.',
  },
  {
    name: 'shrub_fill',
    label: 'Группы кустарника на свободном газоне',
    info: 'Группы кустарника на газоне, пока на улице не наберётся 600 кустов на 1 км (МГСН 1.02-02, табл. В.1).',
  },
  {
    name: 'lawns',
    label: 'Газоны на грунте, свободном от посадок',
    info: 'Новый газон на грунте, который остался свободным после посадок. Только внутри замкнутых контуров чертежа.',
  },
  {
    name: 'root_barriers',
    label: 'Прикорневые барьеры',
    info: 'Барьер в яме защищает сеть от корней. С ним дерево допускается ближе табличного отступа к сетям и борту (СП 42.13330, табл. 9.1, прим. 5 и 7), а барьер становится условием посадки. Без барьеров такие места уходят в отказы с объяснением.',
  },
];

const NEED_SOURCE = 'Выберите улицу пилотного проекта или свой чертёж.';
const NEED_FILE = 'Выберите чертёж или запустите встроенный участок.';

/** Подпись поля со значком определения. Значок - соседом подписи, а не внутри неё: кнопка
 *  внутри label - недопустимая разметка, и клик по ней переключал бы поле. */
function FieldHead({
  htmlFor,
  label,
  children,
}: {
  htmlFor: string;
  label: string;
  children: ReactNode;
}) {
  return (
    <div className="field-head">
      <label htmlFor={htmlFor}>{label}</label>
      <InfoTip term={label}>{children}</InfoTip>
    </div>
  );
}

/** Форма запуска. Параметры свёрнуты: по умолчанию работает профиль целиком, и путь «выбрал
 *  улицу - запустил» не требует ни одного решения; развернуть их нужно для повторного прогона
 *  с другими условиями. demo - каталога улиц нет, его место занимает встроенный участок. */
export function RunForm({ demo = false }: { demo?: boolean }) {
  const navigate = useNavigate();
  const meta = useMeta();
  const streets = useStreets();
  const sample = useDemoStart();
  const ids = useId();

  const [street, setStreet] = useState('');
  const [files, setFiles] = useState<File[]>([]);
  const [extra, setExtra] = useState<File[]>([]);
  const [inventory, setInventory] = useState<File[]>([]);
  const [layers, setLayers] = useState<File[]>([]);
  const [profileName, setProfileName] = useState<string | null>(null);
  const [edited, setEdited] = useState<{ profile: string; values: RunFormValues } | null>(null);
  const [advanced, setAdvanced] = useState('');
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const streetField = useRef<HTMLSelectElement>(null);

  const profileChosen = profileName ?? meta.data?.default_profile;
  const profile = useProfile(profileChosen);
  // Значения формы - это значения выбранного профиля, пока человек их не тронул. Смена
  // профиля сбрасывает правки: они относились к другому набору норм.
  const values =
    profile.data && edited?.profile === profile.data.name
      ? edited.values
      : profile.data
        ? formDefaults(profile.data)
        : null;
  const update = (next: RunFormValues) => {
    if (profile.data) setEdited({ profile: profile.data.name, values: next });
  };

  const hasStreets = Boolean(streets.data?.length);
  // Без каталога и без своего чертежа главное действие - встроенный участок.
  const sampleFirst = demo && !files.length;

  const submit = async (event: SyntheticEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (busy) return;
    if (sampleFirst) {
      void sample.start();
      return;
    }
    const file = files[0];
    if (!street && !file) {
      setMessage(demo ? NEED_FILE : NEED_SOURCE);
      (streetField.current ?? document.getElementById(`${ids}-file`))?.focus();
      return;
    }
    let overrides: Record<string, unknown>;
    try {
      overrides =
        profile.data && values
          ? diffOverrides(profile.data, values, advanced)
          : parseAdvanced(advanced);
    } catch (error) {
      setMessage((error as Error).message);
      return;
    }
    const form = new FormData();
    if (street) {
      form.set('street', street);
    } else if (file) {
      form.set('file', file);
      for (const item of extra) form.append('extra', item);
    }
    if (inventory[0]) form.set('inventory', inventory[0]);
    for (const item of layers) form.append('layers', item);
    if (profileChosen) form.set('profile', profileChosen);
    if (Object.keys(overrides).length) form.set('overrides', JSON.stringify(overrides));

    setMessage('');
    setBusy(true);
    try {
      const run = await postForm<RunOut>('/api/v1/runs', form);
      void navigate(`/runs/${run.id}`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
      setBusy(false);
    }
  };

  const changed = (() => {
    if (!profile.data || !values) return false;
    try {
      return Object.keys(diffOverrides(profile.data, values, advanced)).length > 0;
    } catch {
      return true;
    }
  })();

  const profiles = orderProfiles(meta.data?.profiles ?? []);

  return (
    <form className="start-form" onSubmit={(event) => void submit(event)} noValidate>
      {hasStreets ? (
        <>
          <div className="field">
            <FieldHead htmlFor={`${ids}-street`} label="Улица пилотного проекта">
              Улицы пилотного проекта ДПиООС: подоснова, сети и граница работ уже собраны в
              комплект, загружать файлы не нужно. Улица больше 50 МБ считается несколько минут.
            </FieldHead>
            <select
              id={`${ids}-street`}
              name="street"
              ref={streetField}
              value={street}
              onChange={(event) => {
                setStreet(event.target.value);
                // Улица и свой чертёж - два разных прогона: выбор улицы снимает выбор файла.
                if (event.target.value) setFiles([]);
              }}
            >
              <option value="">не выбрана</option>
              {streets.data?.map((item) => (
                <option key={item.slug} value={item.slug}>
                  {item.number}. {item.title}, {item.size_mb.toFixed(0)} МБ
                </option>
              ))}
            </select>
          </div>
          <p className="or">или</p>
        </>
      ) : demo ? (
        <>
          <div className="field sample">
            <p className="sample-title">Встроенный участок улицы Берзарина</p>
            <p className="hint">
              Фрагмент настоящей подосновы с сетями. Каталог улиц не подключён.
            </p>
          </div>
          <p className="or">или</p>
        </>
      ) : null}

      <FileField
        id={`${ids}-file`}
        label="Свой чертёж подосновы"
        drop
        accept=".dxf,.dwg"
        info="Выгрузка Мосгеотреста, генплан или дендроплан в DXF или DWG. Исходные слои не меняются: план ложится на отдельные слои GREEN_*. Сети и другие файлы того же участка добавляются в параметрах."
        files={files}
        onChange={(next) => {
          setFiles(next);
          if (next.length) setStreet('');
        }}
      />

      <details className="advanced params">
        <summary>
          Параметры: {profileChosen ? profileTitle(profileChosen) : 'профиль'}
          {values ? `, шаг ${plain(values.spacing_m)} м` : ''}
          {changed ? ', изменены' : ''}
        </summary>
        <p className="params-lead">
          Без изменений работает весь профиль. Меняйте параметры, чтобы пересчитать улицу при других
          условиях.
        </p>
        <div className="field-row">
          <div className="field">
            <FieldHead htmlFor={`${ids}-profile`} label="Профиль норм">
              <span className="tip-lead">Готовый набор параметров под исходные данные:</span>
              <span className="tip-list">
                {profiles.map((name) => (
                  <span key={name}>
                    <b>{profileTitle(name)}.</b> {PROFILES[name]?.text ?? ''}
                  </span>
                ))}
              </span>
            </FieldHead>
            <select
              id={`${ids}-profile`}
              name="profile"
              value={profileChosen ?? ''}
              onChange={(event) => {
                setProfileName(event.target.value);
              }}
            >
              {profiles.map((name) => (
                <option key={name} value={name}>
                  {profileTitle(name)}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <FieldHead htmlFor={`${ids}-spacing`} label="Шаг посадки, м">
              Расстояние между соседними посадками в ряду вдоль борта. Для деревьев 743-ПП, табл.
              3.6.2: однорядная посадка 5-6 м, групповая 5-7 м. Вне ряда деревья разносятся по
              размеру взрослых крон.
            </FieldHead>
            <input
              id={`${ids}-spacing`}
              name="spacing_m"
              type="number"
              inputMode="decimal"
              autoComplete="off"
              min={0.5}
              max={20}
              step={0.5}
              value={values?.spacing_m ?? ''}
              disabled={!values}
              onChange={(event) => {
                if (values) update({ ...values, spacing_m: Number(event.target.value) });
              }}
            />
          </div>
        </div>

        <fieldset className="field">
          <legend>
            Приёмы размещения
            <InfoTip term="Приёмы размещения">
              Шаги, которыми сервис заполняет участок: сначала деревья, потом кустарник от борта к
              газону. Снятая галочка пропускает приём, остальные работают как прежде.
            </InfoTip>
          </legend>
          {SWITCHES.map(({ name, label, info }) => (
            <div className="check-row" key={name}>
              <label className="check">
                <input
                  type="checkbox"
                  checked={values ? (name === 'fill' ? values.fill : values.switches[name]) : false}
                  disabled={!values}
                  onChange={(event) => {
                    if (!values) return;
                    const checked = event.target.checked;
                    update(
                      name === 'fill'
                        ? { ...values, fill: checked }
                        : { ...values, switches: { ...values.switches, [name]: checked } },
                    );
                  }}
                />
                {label}
              </label>
              <InfoTip term={label}>{info}</InfoTip>
            </div>
          ))}
        </fieldset>

        <FileField
          id={`${ids}-extra`}
          label="Остальные чертежи комплекта"
          accept=".dxf,.dwg"
          info="Если участок разбит на несколько файлов (сети, дендроизыскания, генплан), добавьте их сюда: сервис склеит их с основным чертежом по координатам. Для улицы из каталога комплект уже собран."
          multiple
          files={extra}
          onChange={setExtra}
        />
        <FileField
          id={`${ids}-inventory`}
          label="Перечётная ведомость"
          accept=".xls,.xlsx"
          info="Опись растущих деревьев в .xls или .xlsx. Существующие породы входят в квоты разнообразия, чтобы сервис не досаживал породу, которой на улице и так много."
          files={inventory}
          onChange={setInventory}
        />
        <FileField
          id={`${ids}-layers`}
          label="Слои ГИС"
          accept=".geojson,.json,.zip"
          info="GeoJSON или SHP в .zip: охранные зоны, здания и границы с data.mos.ru или из кадастра. Координаты WGS 84 пересчитываются в систему координат чертежа."
          multiple
          files={layers}
          onChange={setLayers}
        />
        <div className="field">
          <FieldHead htmlFor={`${ids}-overrides`} label="Параметры поверх профиля, JSON">
            Для точной настройки: любой параметр профиля в JSON, как --set в командной строке.
            Пример в поле: клён остролистный и только аллея вдоль борта. Все параметры перечислены в
            приложении D документации.
          </FieldHead>
          <textarea
            id={`${ids}-overrides`}
            name="overrides"
            autoComplete="off"
            rows={3}
            spellCheck={false}
            value={advanced}
            placeholder='{"species_code": "acer_platanoides", "modes": ["alley"]}'
            onChange={(event) => {
              setAdvanced(event.target.value);
            }}
          />
        </div>
      </details>

      {/* Живая область стоит в разметке всегда: читалка объявляет только изменения внутри
          области, которая существовала до сообщения. */}
      <p className="form-error" role="status" aria-live="polite">
        {message || sample.message}
      </p>
      <button type="submit" className="primary" disabled={busy || sample.busy}>
        {sampleFirst
          ? sample.busy
            ? 'Запускаем…'
            : 'Запустить на встроенном участке'
          : busy
            ? street
              ? 'Готовим улицу…'
              : 'Загружаем чертёж…'
            : 'Запустить прогон'}
      </button>
    </form>
  );
}
