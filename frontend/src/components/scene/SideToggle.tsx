/* Стрелка сворачивания панели 3D-вида к её краю: как на рабочем месте прогона. Свёрнутая
 * панель остаётся квадратной кнопкой у края, стрелка в ней разворачивается обратно (стили
 * .panel-toggle и .hud.collapsed - общие с рабочим местом). Если панелей у края несколько,
 * свёрнутая показывает свой значок и счётчик: так их не спутать. */

import { IconChevron, SceneIcon, type SceneGlyph } from '../icons';

export function SideToggle({
  side,
  collapsed,
  label,
  onToggle,
  icon,
  count,
}: {
  side: 'left' | 'right';
  collapsed: boolean;
  label: string;
  onToggle: () => void;
  /** Значок свёрнутой панели вместо стрелки. */
  icon?: SceneGlyph;
  /** Счётчик на свёрнутой панели, например число снимков. */
  count?: number;
}) {
  const glyph = collapsed && icon;
  return (
    <button
      type="button"
      className="panel-toggle"
      aria-expanded={!collapsed}
      title={collapsed ? `Развернуть: ${label}` : `Свернуть: ${label}`}
      aria-label={`${collapsed ? 'Развернуть' : 'Свернуть'} ${label}`}
      onClick={onToggle}
    >
      {glyph ? <SceneIcon name={glyph} /> : <IconChevron direction={side} />}
      {collapsed && count ? (
        <span className="toggle-count" aria-hidden="true">
          {count}
        </span>
      ) : null}
    </button>
  );
}
