/* Пульт 3D-вида: время суток, сезон, возраст посадок, облачность, качество и снимки. Всё, что
 * меняет картинку, а не план: план правится на рабочем месте прогона. */

import { type ReactNode, useState } from 'react';

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
  /** Сам снимок и что в кадре: по кнопке «в фото» он уходит в нейросеть. */
  blob: Blob;
  viewpoint: 'aerial' | 'ground';
  trees: string[];
  shrubs: string[];
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
  /** Отправить снимок в нейросеть; нет - фото на сервере недоступно. */
  onPhoto?: (shot: Shot) => void;
  /** Раздел «Фото нейросетью»: очередь и готовые фото. */
  photos?: ReactNode;
}

/** Какие разделы пульта открыты: запоминается в браузере, без хранилища - по умолчанию. */
const OPEN_KEY = 'green-scene-sections';

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

export function ScenePanel({
  settings,
  onChange,
  shots,
  onShot,
  busy,
  speed,
  onSpeed,
  onPhoto,
  photos,
}: ScenePanelProps) {
  const [collapsed, setCollapsed] = useState(false);
  const season = SEASONS.find((o) => o.value === settings.season)?.label ?? '';
  const age = AGES.find((o) => o.value === settings.age)?.label ?? '';
  const quality = QUALITIES.find((o) => o.value === settings.quality)?.label ?? '';
  const weather = [
    settings.rain > 0 ? `дождь ${pct(settings.rain)}` : '',
    settings.snow > 0 ? `снег ${pct(settings.snow)}` : '',
    settings.leaves > 0 ? `листопад ${pct(settings.leaves)}` : '',
  ].filter(Boolean);
  return (
    <aside
      className="hud scene-panel"
      aria-label="Пульт 3D-вида"
      data-collapsed={collapsed ? 'true' : undefined}
    >
      <div className="panel-head">
        <span className="panel-title">Пульт</span>
        <button
          type="button"
          className="ghost small"
          aria-expanded={!collapsed}
          onClick={() => {
            setCollapsed((v) => !v);
          }}
        >
          {collapsed ? 'развернуть' : 'свернуть'}
        </button>
      </div>
      {collapsed ? null : (
        <div className="hud-scroll">
          <Section
            id="shots"
            title="Снимки и фото"
            summary={shots.length ? `снимков ${String(shots.length)}` : undefined}
            defaultOpen
          >
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
                      <img
                        src={s.url}
                        alt={`Снимок ${s.width}×${s.height}`}
                        width={96}
                        height={54}
                      />
                    </a>
                    {onPhoto ? (
                      <button
                        type="button"
                        className="ghost small"
                        title="Отправить снимок в нейросеть: фото с той же расстановкой"
                        onClick={() => {
                          onPhoto(s);
                        }}
                      >
                        в фото
                      </button>
                    ) : null}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="hint">
                Снимок скачивается файлом PNG, «в фото» у снимка отправит его в нейросеть.
              </p>
            )}
            {photos}
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
            <Segmented
              label="Сезон"
              options={SEASONS}
              value={settings.season}
              onChange={(value) => {
                onChange({ season: value });
              }}
            />
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
          </Section>
          <Section
            id="plants"
            title="Посадки"
            summary={`${age}${settings.showExisting ? ', с существующими' : ''}`}
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
            id="weather"
            title="Погода"
            summary={weather.length ? weather.join(', ') : `ветер ${pct(settings.wind)}`}
          >
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
            <Share
              id="scene-people"
              label="Люди на тротуарах"
              value={settings.people}
              onChange={(people) => {
                onChange({ people });
              }}
            />
            <Segmented
              label="Качество"
              options={QUALITIES}
              value={settings.quality}
              onChange={(value) => {
                onChange({ quality: value });
              }}
            />
          </Section>
        </div>
      )}
    </aside>
  );
}
