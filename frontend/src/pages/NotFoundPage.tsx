import { Link } from 'react-router';

export function NotFoundPage() {
  return (
    <div className="launch">
      <div className="panel" style={{ maxWidth: 560, margin: '0 auto' }}>
        <h1 className="start-title">Такой страницы нет</h1>
        <p className="hint">
          <Link to="/">← все прогоны</Link>
        </p>
      </div>
    </div>
  );
}
