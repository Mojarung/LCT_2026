import { IconMoon, IconSun } from './icons';

/** Переключатель темы. Действующая тема читается по её фактическому эффекту (--is-dark), а не
 *  по тому, что ей назначили: иначе при системной теме кнопка «работает», ничего не переключая. */
export function ThemeToggle() {
  const toggle = () => {
    const root = document.documentElement;
    const dark = getComputedStyle(root).getPropertyValue('--is-dark').trim() === '1';
    const next = dark ? 'light' : 'dark';
    root.dataset.theme = next;
    try {
      localStorage.setItem('green-theme', next);
    } catch {
      /* приватный режим: тема не переживёт перезагрузку */
    }
  };
  return (
    <button type="button" onClick={toggle} title="Переключить тему" aria-label="Переключить тему">
      {/* Показывается значок темы, в которую переведёт нажатие: в тёмной - солнце. */}
      <IconSun className="icon icon-sun" />
      <IconMoon className="icon icon-moon" />
    </button>
  );
}
