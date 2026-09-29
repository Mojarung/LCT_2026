/* Кнопка полосы 3D-вида: значок, подпись и клавиша. Клавиша видна на самой кнопке, поэтому
 * подсказка по центру экрана больше не перечисляет их все. */

import { SceneIcon, type SceneGlyph } from '../icons';

export interface BarButtonProps {
  icon: SceneGlyph;
  label: string;
  keyHint?: string;
  title: string;
  pressed?: boolean;
  disabled?: boolean;
  /** Главное действие группы: фото нейросетью. */
  accent?: boolean;
  /** Значок крутится: модель ещё рисует. */
  spin?: boolean;
  onClick: () => void;
}

export function BarButton({
  icon,
  label,
  keyHint,
  title,
  pressed,
  disabled,
  accent,
  spin,
  onClick,
}: BarButtonProps) {
  return (
    <button
      type="button"
      className={accent ? 'bar-button accent' : 'bar-button'}
      aria-pressed={pressed}
      disabled={disabled}
      title={keyHint ? `${title}. Клавиша ${keyHint}` : title}
      aria-keyshortcuts={keyHint}
      onClick={onClick}
    >
      <SceneIcon name={icon} className={spin ? 'icon spin' : 'icon'} />
      <span>{label}</span>
      {keyHint ? (
        <kbd className="bar-key" aria-hidden="true">
          {keyHint}
        </kbd>
      ) : null}
    </button>
  );
}
