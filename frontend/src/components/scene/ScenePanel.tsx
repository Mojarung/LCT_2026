/* Пульт 3D-вида: время суток, сезон, возраст посадок, облачность, качество и снимки. Всё, что
 * меняет картинку, а не план: план правится на рабочем месте прогона. */

import { type ReactNode, useEffect, useRef, useState } from 'react';

import type { Quality, ViewSettings } from '../../scene3d/engine';
import { FLY_SPEED_MAX, FLY_SPEED_MIN } from '../../scene3d/freecam';
import { PLAN_YEAR } from '../../scene3d/growth';
import { clock, showcaseHour, type Season } from '../../scene3d/solar';
import { useSideCollapsed } from '../../hooks/useSideCollapsed';
import { SideToggle } from './SideToggle';

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
  speed: number;
  onSpeed: (speed: number) => void;
}

/** Какие разделы пульта открыты: запоминается в браузере, без хранилища - по умолчанию. */
// v2: разделы переставлены 17.10.2026, прежние открытые и свёрнутые не переносятся.
const OPEN_KEY = 'green-scene-sections-v2';

function readOpen(): Record<string, boolean> {
  try {
    return JSON.parse(localStorage.getItem(OPEN_KEY) ?? '{}') as Record<string, boolean>;
  } catch {
    return {};
  }
}

function writeOpen(id: string, open: boolean): void {
  try {
    localStorage.setItem(OPEN_KEY, JSON.stringify({ ...readOpen(), [id]: open }));
  } catch {
    /* без хранилища раздел просто откроется как по умолчанию */
  }
}

/** Раздел пульта: заголовок со сводкой значений, содержимое сворачивается. */
function Section({
  id,
  title,
  summary,
  defaultOpen = false,
  children,
}: {
  id: string;
  title: string;
  summary?: string;
  defaultOpen?: boolean;
  children: ReactNode;
}) {
  const open = readOpen()[id] ?? defaultOpen;
  return (
    <details
      className="scene-section"
      open={open}
      onToggle={(e) => {
        writeOpen(id, e.currentTarget.open);
      }}
    >
      <summary>
        <span className="section-title">{title}</span>
        {summary ? <span className="section-summary">{summary}</span> : null}
      </summary>
      <div className="section-body">{children}</div>
    </details>
  );
}

const pct = (v: number) => `${String(Math.round(v * 100))}%`;

/** Прокрутка суток: шаг часа и период, сутки - за 24 с. */
const SPIN_STEP_H = 0.1;
const SPIN_TICK_MS = 100;

/** Сутки идут сами, пока включена прокрутка: час сдвигается по таймеру, свет догоняет его. */
function useDaySpin(hour: number, onHour: (hour: number) => void): [boolean, () => void] {
  const [spinning, setSpinning] = useState(false);
  const current = useRef(hour);
  const push = useRef(onHour);
  useEffect(() => {
    current.current = hour;
    push.current = onHour;
  });
  useEffect(() => {
    if (!spinning) return undefined;
    const timer = window.setInterval(() => {
      push.current(Math.round(((current.current + SPIN_STEP_H) % 24) * 100) / 100);
    }, SPIN_TICK_MS);
    return () => {
      window.clearInterval(timer);
    };
  }, [spinning]);
  return [
    spinning,
    () => {
      setSpinning((on) => !on);
    },
  ];
}

const turnLabel = (turn: number) =>
  turn === 0 ? 'как над Москвой' : `${turn > 0 ? '+' : ''}${String(turn)}°`;

export function ScenePanel({ settings, onChange, speed, onSpeed }: ScenePanelProps) {
  const [collapsed, toggle] = useSideCollapsed('green-scene-right');
  const [spinning, toggleSpin] = useDaySpin(settings.hour, (hour) => {
    onChange({ hour });
  });
  const season = SEASONS.find((o) => o.value === settings.season)?.label ?? '';
  const age = AGES.find((o) => o.value === settings.age)?.label ?? '';
  const quality = QUALITIES.find((o) => o.value === settings.quality)?.label ?? '';
  const weather = [
    settings.rain > 0 ? `дождь ${pct(settings.rain)}` : '',
    settings.snow > 0 ? `снег ${pct(settings.snow)}` : '',
    settings.leaves > 0 ? `листопад ${pct(settings.leaves)}` : '',
  ].filter(Boolean);
  const weatherSummary = weather.length
    ? weather.join(', ')
    : `облачно ${pct(settings.clouds)}, ветер ${pct(settings.wind)}`;
  const surroundings =
    [
      settings.people > 0 ? `люди ${pct(settings.people)}` : '',
      settings.cars ? 'машины' : '',
      settings.extras ? 'обстановка' : '',
      settings.city ? 'город' : '',
    ]
      .filter(Boolean)
      .join(', ') || 'пусто';
  return (
    <aside
      className={collapsed ? 'hud scene-panel collapsed' : 'hud scene-panel'}
      aria-label="Пульт 3D-вида"
    >
      <SideToggle side="right" collapsed={collapsed} label="пульт" onToggle={toggle} />
      <div className="panel-head">
        <span className="panel-title">Пульт</span>
      </div>
      {collapsed ? null : (
        <div className="hud-scroll">
          {/* Порядок - по тому, что спрашивают на показе: как посадки будут выглядеть с годами
              и при каком свете. Камера, окружение и погода - ниже и свёрнуты. */}
          <Section
            id="plants"
            title="Посадки"
            summary={`${age}${settings.showExisting ? ', с существующими' : ''}`}
            defaultOpen
          >
            <Segmented
              label="Возраст посадок"
              options={AGES}
              value={settings.age}
              onChange={(value) => {
                onChange({ age: value });
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
          </Section>
          <Section
            id="time"
            title="Время и сезон"
            summary={`${clock(settings.hour)}, ${season}`}
            defaultOpen
          >
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
            <button
              className="ghost small scene-day-spin"
              type="button"
              aria-pressed={spinning}
              onClick={toggleSpin}
            >
              {spinning ? 'Остановить сутки' : 'Прокрутить сутки'}
            </button>
            <div className="scene-field">
              <label className="hud-label" htmlFor="scene-sun-turn">
                Поворот солнца <span className="scene-value">{turnLabel(settings.sunTurn)}</span>
              </label>
              <input
                id="scene-sun-turn"
                type="range"
                min={-180}
                max={180}
                step={5}
                value={settings.sunTurn}
                onChange={(e) => {
                  onChange({ sunTurn: Number(e.target.value) });
                }}
              />
            </div>
            <Segmented
              label="Сезон"
              options={SEASONS}
              value={settings.season}
              onChange={(value) => {
                onChange({ season: value });
              }}
            />
            <button
              className="ghost small scene-light-preset"
              type="button"
              onClick={() => {
                onChange({ hour: showcaseHour(settings.season), clouds: 0.2 });
              }}
            >
              Поставить мягкий вечерний свет
            </button>
          </Section>
          <Section
            id="layers"
            title="Слои плана"
            summary={
              [settings.utilities ? 'сети' : '', settings.boundary ? 'граница' : '']
                .filter(Boolean)
                .join(', ') || 'выключены'
            }
          >
            <label className="check">
              <input
                type="checkbox"
                checked={settings.utilities}
                onChange={(e) => {
                  onChange({ utilities: e.target.checked });
                }}
              />
              Подземные сети - цветами плана
            </label>
            <label className="check">
              <input
                type="checkbox"
                checked={settings.boundary}
                onChange={(e) => {
                  onChange({ boundary: e.target.checked });
                }}
              />
              Граница работ
            </label>
            <p className="hint">В кадры для фото ИИ слои не попадают.</p>
          </Section>
          <Section
            id="camera"
            title="Камера и качество"
            summary={`${String(Math.round(speed))} м/с, ${quality}`}
          >
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
                aria-valuetext={`${String(Math.round(speed))} метров в секунду`}
                onChange={(e) => {
                  onSpeed(fromSlider(Number(e.target.value)));
                }}
              />
            </div>
            <Segmented
              label="Качество"
              options={QUALITIES}
              value={settings.quality}
              onChange={(value) => {
                onChange({ quality: value });
              }}
            />
            <label className="check">
              <input
                type="checkbox"
                checked={settings.enhanced}
                disabled={settings.quality === 'low'}
                onChange={(e) => {
                  onChange({ enhanced: e.target.checked });
                }}
              />
              Объёмный свет и сглаживание
            </label>
          </Section>
          <Section id="surroundings" title="Окружение" summary={surroundings}>
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
                checked={settings.cars}
                onChange={(e) => {
                  onChange({ cars: e.target.checked });
                }}
              />
              Машины у бортов (условно: в подоснове их нет)
            </label>
            <label className="check">
              <input
                type="checkbox"
                checked={settings.extras}
                onChange={(e) => {
                  onChange({ extras: e.target.checked });
                }}
              />
              Скамейки, урны, оборудование площадок, люки, лунки (условно: в чертеже их нет)
            </label>
            <label className="check">
              <input
                type="checkbox"
                checked={settings.city}
                onChange={(e) => {
                  onChange({ city: e.target.checked });
                }}
              />
              Город вокруг съёмки (OpenStreetMap)
            </label>
          </Section>
          <Section id="weather" title="Погода" summary={weatherSummary}>
            <div className="scene-field">
              <label className="hud-label" htmlFor="scene-clouds">
                Облачность <span className="scene-value">{pct(settings.clouds)}</span>
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
          </Section>
        </div>
      )}
    </aside>
  );
}
