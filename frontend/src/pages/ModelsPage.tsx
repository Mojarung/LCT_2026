import ModelsCatalog from '../components/ModelsCatalog';

/** База моделей отдельной страницей: заголовок и каталог. На прогоне тот же каталог
 *  открывается окном из шапки, чтобы не уходить с рабочего места. */
export function ModelsPage() {
  return (
    <div className="launch">
      <div className="sheet">
        <header className="stamp">
          <div className="stamp-title">
            <h1>Модели растений</h1>
            <p>
              Чем каждый вид каталога нарисован на плане: форма кроны, листва, цветение и плоды.
            </p>
          </div>
        </header>
        <ModelsCatalog />
      </div>
    </div>
  );
}
