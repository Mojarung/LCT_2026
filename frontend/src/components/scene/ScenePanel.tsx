/* Пульт 3D-вида: время суток, сезон, возраст посадок, облачность, качество и снимки. Всё, что
 * меняет картинку, а не план: план правится на рабочем месте прогона. */

import type { Quality, ViewSettings } from '../../scene3d/engine';
import { FLY_SPEED_MAX, FLY_SPEED_MIN } from '../../scene3d/freecam';
import { PLAN_YEAR } from '../../scene3d/growth';
import { clock, type Season } from '../../scene3d/solar';

export interface Shot {
  id: number;
  url: string;
  name: string;
  width: number;
  height: number;
}

const SEASONS: { value: Season; label: string }[] = [
  { value: 'spring', label: 'весна' },
  { value: 'summer', label: 'лето' },
  { value: 'autumn', label: 'осень' },
  { value: 'winter', label: 'зима' },
];

const AGES: { value: number; label: string; title: string }[] = [
  { value: 0, label: 'посадка', title: 'Крупномер в год посадки' },
  { value: PLAN_YEAR, label: '10 лет', title: 'Крона как условный знак на плане' },
  { value: 25, label: '25 лет', title: 'Сомкнутые кроны аллеи' },
  { value: 60, label: 'взрослые', title: 'Взрослая высота и крона по каталогу' },
];

const QUALITIES: { value: Quality; label: string }[] = [
  { value: 'low', label: 'быстро' },
  { value: 'medium', label: 'обычно' },
  { value: 'high', label: 'красиво' },
];

/** Ползунок силы 0..100%: погода и люди. */
function Share({
  id,
  label,
  value,
  onChange,
}: {
  id: string;
  label: string;
  value: number;
  onChange: (value: number) => void;
}) {
  return (
    <div className="scene-field">
      <label className="hud-label" htmlFor={id}>
        {label} <span className="scene-value">{Math.round(value * 100)}%</span>
      </label>
      <input
        id={id}
        type="range"
        min={0}
        max={1}
        step={0.05}
        value={value}
        onChange={(e) => {
          onChange(Number(e.target.value));
        }}
      />
    </div>
  );
}

function Segmented<T extends string | number>({
  label,
  options,
  value,
  onChange,
}: {
  label: string;
  options: { value: T; label: string; title?: string }[];
  value: T;
  onChange: (value: T) => void;
}) {
  return (
    <div className="scene-field" role="radiogroup" aria-label={label}>
      <span className="hud-label">{label}</span>
      <div className="segmented">
        {options.map((o) => (
          <button
            key={String(o.value)}
            type="button"
            role="radio"
            aria-checked={o.value === value}
            title={o.title}
            onClick={() => {
              onChange(o.value);
            }}
          >
            {o.label}
          </button>
        ))}
      </div>
    </div>
  );
}

/** Ползунок скорости - в логарифмической шкале: 1-10 м/с нужны точно, 30-60 - грубо. */
const SPEED_STEPS = 100;
const SPEED_SPAN = Math.log(FLY_SPEED_MAX / FLY_SPEED_MIN);
const toSlider = (speed: number) =>
  Math.round((Math.log(speed / FLY_SPEED_MIN) / SPEED_SPAN) * SPEED_STEPS);
const fromSlider = (value: number) => FLY_SPEED_MIN * Math.exp((value / SPEED_STEPS) * SPEED_SPAN);

export interface ScenePanelProps {
  settings: ViewSettings;
  onChange: (patch: Partial<ViewSettings>) => void;
  shots: Shot[];
  onShot: (scale: number) => void;
  busy: boolean;
  speed: number;
  onSpeed: (speed: number) => void;
}

export function ScenePanel({
  settings,
  onChange,
  shots,
  onShot,
  busy,
  speed,
  onSpeed,
}: ScenePanelProps) {
  return (
    <aside className="hud scene-panel" aria-label="Настройки 3D-вида">
      <div className="hud-scroll">
        <div className="scene-field">
          <label className="hud-label" htmlFor="scene-hour">
            Время суток <span className="scene-value">{clock(settings.hour)}</span>
          </label>
          <input
            id="scene-hour"
            type="range"
            min={0}
            max={24}
            step={0.25}
            value={settings.hour}
            onChange={(e) => {
              onChange({ hour: Number(e.target.value) });
            }}
          />
        </div>
        <div className="scene-field">
          <label className="hud-label" htmlFor="scene-speed">
            Скорость полёта <span className="scene-value">{Math.round(speed)} м/с</span>
          </label>
          <input
            id="scene-speed"
            type="range"
            min={0}
            max={SPEED_STEPS}
            step={1}
            value={toSlider(speed)}
            aria-valuetext={`${Math.round(speed)} метров в секунду`}
            onChange={(e) => {
              onSpeed(fromSlider(Number(e.target.value)));
            }}
          />
        </div>
        <Segmented
          label="Сезон"
          options={SEASONS}
          value={settings.season}
          onChange={(season) => {
            onChange({ season });
          }}
        />
        <Segmented
          label="Возраст посадок"
          options={AGES}
          value={settings.age}
          onChange={(age) => {
            onChange({ age });
          }}
        />
        <div className="scene-field">
          <label className="hud-label" htmlFor="scene-clouds">
            Облачность <span className="scene-value">{Math.round(settings.clouds * 100)}%</span>
          </label>
          <input
            id="scene-clouds"
            type="range"
            min={0}
            max={0.9}
            step={0.05}
            value={settings.clouds}
            onChange={(e) => {
              onChange({ clouds: Number(e.target.value) });
            }}
          />
        </div>
        <Share
          id="scene-wind"
          label="Ветер"
          value={settings.wind}
          onChange={(wind) => {
            onChange({ wind });
          }}
        />
        <Share
          id="scene-rain"
          label="Дождь"
          value={settings.rain}
          onChange={(rain) => {
            onChange({ rain });
          }}
        />
        <Share
          id="scene-snow"
          label="Снег"
          value={settings.snow}
          onChange={(snow) => {
            onChange({ snow });
          }}
        />
        <Share
          id="scene-leaves"
          label="Листопад"
          value={settings.leaves}
          onChange={(leaves) => {
            onChange({ leaves });
          }}
        />
        <Share
          id="scene-people"
          label="Люди на тротуарах"
          value={settings.people}
          onChange={(people) => {
            onChange({ people });
          }}
        />
        <label className="check">
          <input
            type="checkbox"
            checked={settings.showExisting}
            onChange={(e) => {
              onChange({ showExisting: e.target.checked });
            }}
          />
          Существующие насаждения с подосновы
        </label>
        <Segmented
          label="Качество"
          options={QUALITIES}
          value={settings.quality}
          onChange={(quality) => {
            onChange({ quality });
          }}
        />
        <div className="scene-field">
          <span className="hud-label">Снимки</span>
          <div className="scene-shot-buttons">
            <button
              type="button"
              className="primary small"
              disabled={busy}
              title="Снимок кадра, клавиша P"
              onClick={() => {
                onShot(1);
              }}
            >
              снимок
            </button>
            <button
              type="button"
              className="ghost small"
              disabled={busy}
              title="Вдвое больше по каждой стороне, для слайда"
              onClick={() => {
                onShot(2);
              }}
            >
              снимок ×2
            </button>
          </div>
          {shots.length ? (
            <ul className="scene-shots">
              {shots.map((s) => (
                <li key={s.id}>
                  <a href={s.url} download={s.name} title={`Скачать ${s.name}`}>
                    <img src={s.url} alt={`Снимок ${s.width}×${s.height}`} width={96} height={54} />
                    <span>
                      {s.width}×{s.height}
                    </span>
                  </a>
                </li>
              ))}
            </ul>
          ) : (
            <p className="hint">
              Снимок сохраняется файлом PNG и остаётся здесь до ухода со страницы.
            </p>
          )}
        </div>
      </div>
    </aside>
  );
}
