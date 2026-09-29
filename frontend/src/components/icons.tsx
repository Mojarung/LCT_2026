/* Значки из Tabler: штриховые, как и весь интерфейс, и лежат в бандле - офлайновому стенду
 * CDN не нужен. Один размер и одна толщина штриха на всё приложение. */

import {
  type Icon,
  IconBook as TablerBook,
  IconCamera,
  IconChevronLeft,
  IconChevronRight,
  IconDrone,
  IconEyeOff,
  IconHome,
  IconLayoutGrid,
  IconLoader2,
  IconMoon as TablerMoon,
  IconPencil,
  IconPlane,
  IconRoad,
  IconSparkles,
  IconSun as TablerSun,
  IconTrash,
  IconWalk,
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

/** Значки полосы 3D-вида: режим камеры, облёт, снимок, фото нейросетью, кадры, панели. */
const SCENE_GLYPHS = {
  fly: IconPlane,
  walk: IconWalk,
  overview: IconHome,
  tour: IconDrone,
  snapshot: IconCamera,
  photo: IconSparkles,
  shots: IconLayoutGrid,
  hide: IconEyeOff,
  spinner: IconLoader2,
  prompt: IconPencil,
  street: IconRoad,
} satisfies Record<string, Icon>;

export type SceneGlyph = keyof typeof SCENE_GLYPHS;

export function SceneIcon({ name, className = 'icon' }: IconProps & { name: SceneGlyph }) {
  const Glyph = SCENE_GLYPHS[name];
  return <Glyph className={className} size={SIZE} stroke={STROKE} aria-hidden="true" />;
}

export function IconDelete({ className = 'icon' }: IconProps) {
  return <IconTrash className={className} size={SIZE} stroke={STROKE} aria-hidden="true" />;
}
