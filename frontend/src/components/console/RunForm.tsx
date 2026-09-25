import { useId, useRef, useState, type SyntheticEvent } from 'react';
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
import { useDemoStart } from './DemoStart';
import { FileField } from './FileField';

/** Приёмы по порядку работы конвейера: деревья, потом кустарник от борта к газону. Две строки
 *  про группы кустарника различаются тем, откуда место: пустое после квот деревьев или
 *  свободный газон. */
const SWITCH_LABELS: { name: Switch | 'fill'; label: string }[] = [
  { name: 'fill', label: 'Добор зоны: узкие полосы и карманы газона' },
  { name: 'shrub_rows', label: 'Ряд кустарника у борта под кронами аллеи' },
  { name: 'curb_hedges', label: 'Живая изгородь вдоль остальных бортов, до 720 кустов на 1 км' },
  { name: 'understory', label: 'Кустарник под кроной дерева, где ряда нет' },
  { name: 'shrub_groups', label: 'Кустарник там, где квоты не пустили дерево' },
  { name: 'shrub_fill', label: 'Группы кустарника на свободном газоне' },
  { name: 'root_barriers', label: 'Прикорневые барьеры' },
];

const NEED_SOURCE = 'Выберите улицу пилотного проекта или свой чертёж.';
const NEED_FILE = 'Выберите чертёж или запустите встроенный участок.';

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

  return (
    <form className="start-form" onSubmit={(event) => void submit(event)} noValidate>
      {hasStreets ? (
        <>
          <div className="field">
            <label htmlFor={`${ids}-street`}>Улица пилотного проекта</label>
            <select
              id={`${ids}-street`}
              name="street"
              ref={streetField}
              value={street}
              aria-describedby={`${ids}-street-hint`}
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
            <p className="hint" id={`${ids}-street-hint`}>
              Чертежи крупнее полусотни мегабайт считаются минутами.
            </p>
          </div>
          <p className="or">или</p>
        </>
      ) : demo ? (
        <>
          <div className="field sample">
            <p className="sample-title">Встроенный участок улицы Берзарина</p>
            <p className="hint">
              Фрагмент настоящей подосновы с сетями: каталог улиц не подключён.
            </p>
          </div>
          <p className="or">или</p>
        </>
      ) : null}

      <FileField
        id={`${ids}-file`}
        label="Свой чертёж подосновы"
        accept=".dxf,.dwg"
        hint="DXF или DWG: выгрузка Мосгеотреста, генплан, дендроплан."
        files={files}
        onChange={(next) => {
          setFiles(next);
          if (next.length) setStreet('');
        }}
      />

      <details className="advanced params">
        <summary>
          Параметры: {profileChosen ?? 'профиль'}
          {values ? `, шаг ${plain(values.spacing_m)} м` : ''}
          {changed ? ', изменены' : ''}
        </summary>
        <div className="field-row">
          <div className="field">
            <label htmlFor={`${ids}-profile`}>Профиль норм</label>
            <select
              id={`${ids}-profile`}
              name="profile"
              value={profileChosen ?? ''}
              onChange={(event) => {
                setProfileName(event.target.value);
              }}
            >
              {meta.data?.profiles.map((name) => (
                <option key={name} value={name}>
                  {name}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor={`${ids}-spacing`}>Шаг посадки, м</label>
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
              aria-describedby={`${ids}-spacing-hint`}
              onChange={(event) => {
                if (values) update({ ...values, spacing_m: Number(event.target.value) });
              }}
            />
            <p className="hint" id={`${ids}-spacing-hint`}>
              743-ПП, табл. 3.6.2: однорядная посадка 5-6 м, групповая 5-7 м.
            </p>
          </div>
        </div>

        <fieldset className="field">
          <legend>Приёмы размещения</legend>
          {SWITCH_LABELS.map(({ name, label }) => (
            <label className="check" key={name}>
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
          ))}
          <p className="hint">Сокращённые отступы по прим. 5 и 7 табл. 9.1 СП 42.13330.</p>
        </fieldset>

        <FileField
          id={`${ids}-extra`}
          label="Остальные чертежи комплекта"
          accept=".dxf,.dwg"
          hint="Склеиваются с основным: сети, дендроизыскания, генплан. С улицей из каталога не нужны."
          multiple
          files={extra}
          onChange={setExtra}
        />
        <FileField
          id={`${ids}-inventory`}
          label="Перечётная ведомость"
          accept=".xls,.xlsx"
          hint="Растущие деревья входят в квоты разнообразия."
          files={inventory}
          onChange={setInventory}
        />
        <div className="field">
          <label htmlFor={`${ids}-overrides`}>Параметры поверх профиля, JSON</label>
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
