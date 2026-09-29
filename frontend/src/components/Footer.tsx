import { Link } from 'react-router';

import { useMeta } from '../api/queries';

export function Footer() {
  const meta = useMeta();
  return (
    <footer className="footer">
      <span className="mono">green{meta.data ? ` ${meta.data.version}` : ''}</span>
      {/* /docs отдаёт сервер, а не роутер: обычная ссылка. */}
      <a href="/docs">HTTP API и Swagger</a>
      <Link to="/models">Модели растений</Link>
    </footer>
  );
}
