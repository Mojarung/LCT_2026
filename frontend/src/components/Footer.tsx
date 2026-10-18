import { Link } from 'react-router';

import { useMeta } from '../api/queries';

/** Подвал - закрытие страницы: полный логотип с подписью, справа справочные ссылки и версия. */
export function Footer() {
  const meta = useMeta();
  return (
    <footer className="footer">
      <span className="footer-logo">
        <img
          className="theme-light"
          src="/logo-full.webp"
          width={196}
          height={64}
          alt="GREEN_ - озеленение по нормам"
          loading="lazy"
        />
        <img
          className="theme-dark"
          src="/logo-full-dark.webp"
          width={196}
          height={64}
          alt="GREEN_ - озеленение по нормам"
          loading="lazy"
        />
      </span>
      <nav className="footer-links" aria-label="Справка">
        {/* /docs отдаёт сервер, а не роутер: обычная ссылка. */}
        <a href="/docs">HTTP API и Swagger</a>
        <Link to="/models">Модели растений</Link>
        <span className="num">{meta.data ? `версия ${meta.data.version}` : ''}</span>
      </nav>
    </footer>
  );
}
