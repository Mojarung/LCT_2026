/* Пульт 3D-вида: время суток, сезон, возраст посадок, облачность, качество и снимки. Всё, что
 * меняет картинку, а не план: план правится на рабочем месте прогона. */

import type { Quality, ViewSettings } from '../../scene3d/engine';
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

export interface ScenePanelProps {
  settings: ViewSettings;
  onChange: (patch: Partial<ViewSettings>) => void;
  shots: Shot[];
  onShot: (scale: number) => void;
  busy: boolean;
}

export function ScenePanel({ settings, onChange, shots, onShot, busy }: ScenePanelProps) {
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
            min={5}
            max={22}
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
              title="Вдвое больше пикселей, для слайда"
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
