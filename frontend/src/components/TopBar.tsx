import { IconBook } from './icons';
import { ThemeToggle } from './ThemeToggle';

/** Шапка - одна пилюля значков поверх плана, без полосы во всю ширину: полоса отрезала бы от
 *  карты пятьдесят пикселей, которые на участке-ленте дороже заголовка. */
export function TopBar() {
  return (
    <header className="topbar">
      <nav className="topbar-nav" aria-label="Сервис">
        {/* Обычная ссылка, а не переход роутера: /docs отдаёт сервер. */}
        <a href="/docs" title="Документация API (Swagger)" aria-label="Документация API">
          <IconBook />
        </a>
        <ThemeToggle />
      </nav>
    </header>
  );
}
