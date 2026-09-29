/* Значки из Tabler: штриховые, как и весь интерфейс, и лежат в бандле - офлайновому стенду
 * CDN не нужен. Один размер и одна толщина штриха на всё приложение. */

import {
  IconBook as TablerBook,
  IconChevronLeft,
  IconChevronRight,
  IconMoon as TablerMoon,
  IconSun as TablerSun,
  IconTrash,
  IconX,
} from '@tabler/icons-react';

const SIZE = 18;
const STROKE = 1.6;

interface IconProps {
  className?: string;
}

export function IconBook({ className = 'icon' }: IconProps) {
  return <TablerBook className={className} size={SIZE} stroke={STROKE} aria-hidden="true" />;
}

export function IconSun({ className = 'icon' }: IconProps) {
  return <TablerSun className={className} size={SIZE} stroke={STROKE} aria-hidden="true" />;
}

export function IconMoon({ className = 'icon' }: IconProps) {
  return <TablerMoon className={className} size={SIZE} stroke={STROKE} aria-hidden="true" />;
}

export function IconClose({ className = 'icon' }: IconProps) {
  return <IconX className={className} size={SIZE} stroke={STROKE} aria-hidden="true" />;
}

export function IconChevron({
  direction,
  className = 'icon chev',
}: IconProps & { direction: 'left' | 'right' }) {
  const Glyph = direction === 'left' ? IconChevronLeft : IconChevronRight;
  return <Glyph className={className} size={SIZE} stroke={STROKE} aria-hidden="true" />;
}

export function IconDelete({ className = 'icon' }: IconProps) {
  return <IconTrash className={className} size={SIZE} stroke={STROKE} aria-hidden="true" />;
}
