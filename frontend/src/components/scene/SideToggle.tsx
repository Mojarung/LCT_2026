/* Стрелка сворачивания панели 3D-вида к её краю: как на рабочем месте прогона. Свёрнутая
 * панель остаётся квадратной кнопкой у края, стрелка в ней разворачивается обратно (стили
 * .panel-toggle и .hud.collapsed - общие с рабочим местом). */

import { IconChevron } from '../icons';

export function SideToggle({
  side,
  collapsed,
  label,
  onToggle,
}: {
  side: 'left' | 'right';
  collapsed: boolean;
  label: string;
  onToggle: () => void;
}) {
  return (
    <button
      type="button"
      className="panel-toggle"
      aria-expanded={!collapsed}
      title={collapsed ? 'Развернуть панель' : 'Свернуть панель'}
      aria-label={`${collapsed ? 'Развернуть' : 'Свернуть'} ${label}`}
      onClick={onToggle}
    >
      <IconChevron direction={side} />
    </button>
  );
}
