import type { RouteObject } from 'react-router';

import { Layout } from './components/Layout';
import { ConsolePage } from './pages/ConsolePage';
import { NotFoundPage } from './pages/NotFoundPage';

/** Два рабочих экрана - консоль запуска и рабочее место прогона, - уточнение объектов чертежа
 *  для строгого прогона, 3D-вид участка со снимками и справочная база моделей растений. Остальные адреса - API и /docs, их
 *  отдаёт сервер, а не приложение. */
export const routes: RouteObject[] = [
  {
    path: '/',
    Component: Layout,
    children: [
      { index: true, Component: ConsolePage },
      // Карта, уточнение и модели - своими чанками: главная не качает код карты.
      {
        path: 'runs/:runId',
        lazy: async () => ({ Component: (await import('./pages/RunPage')).RunPage }),
      },
      {
        path: 'runs/:runId/review',
        lazy: async () => ({ Component: (await import('./pages/ReviewPage')).ReviewPage }),
      },
      // three.js и модели крон - отдельным чанком: тем, кто 3D не открывает, их не качать.
      {
        path: 'runs/:runId/3d',
        lazy: async () => ({ Component: (await import('./pages/ScenePage')).ScenePage }),
      },
      {
        path: 'models',
        lazy: async () => ({ Component: (await import('./pages/ModelsPage')).ModelsPage }),
      },
      { path: '*', Component: NotFoundPage },
    ],
  },
];
