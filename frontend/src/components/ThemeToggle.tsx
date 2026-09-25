import { IconMoon, IconSun } from './icons';

/** Переключатель темы. Действующая тема читается по её фактическому эффекту (--is-dark), а не
 *  по тому, что ей назначили: иначе при системной теме кнопка «работает», ничего не переключая. */
export function ThemeToggle() {
  const toggle = () => {
    const root = document.documentElement;
    const dark = getComputedStyle(root).getPropertyValue('--is-dark').trim() === '1';
    const next = dark ? 'light' : 'dark';
    root.dataset.theme = next;
    // Строка браузера на телефоне красится в фон страницы, а не в системную тему.
    const ground = getComputedStyle(root).getPropertyValue('--ground').trim();
    for (const meta of document.querySelectorAll<HTMLMetaElement>('meta[name="theme-color"]')) {
      meta.content = ground;
    }
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
