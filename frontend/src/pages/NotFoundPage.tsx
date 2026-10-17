import { Link } from 'react-router';

export function NotFoundPage() {
  return (
    <div className="empty-page">
      <h1>Такой страницы нет</h1>
      <p>Адрес мог устареть: прогон удалили или ссылку скопировали не целиком.</p>
      <Link className="primary" to="/">
        ← все прогоны
      </Link>
    </div>
  );
}
