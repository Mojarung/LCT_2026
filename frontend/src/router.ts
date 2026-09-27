import type { RouteObject } from 'react-router';

import { Layout } from './components/Layout';
import { ConsolePage } from './pages/ConsolePage';
import { ModelsPage } from './pages/ModelsPage';
import { NotFoundPage } from './pages/NotFoundPage';
import { ReviewPage } from './pages/ReviewPage';
import { RunPage } from './pages/RunPage';

/** Два рабочих экрана - консоль запуска и рабочее место прогона, - уточнение объектов чертежа
 *  для строгого прогона, 3D-вид участка со снимками и справочная база моделей растений. Остальные адреса - API и /docs, их
 *  отдаёт сервер, а не приложение. */
export const routes: RouteObject[] = [
  {
    path: '/',
    Component: Layout,
    children: [
      { index: true, Component: ConsolePage },
      { path: 'runs/:runId', Component: RunPage },
      { path: 'runs/:runId/review', Component: ReviewPage },
      // three.js и модели крон - отдельным чанком: тем, кто 3D не открывает, их не качать.
      {
        path: 'runs/:runId/3d',
        lazy: async () => ({ Component: (await import('./pages/ScenePage')).ScenePage }),
      },
      { path: 'models', Component: ModelsPage },
      { path: '*', Component: NotFoundPage },
    ],
  },
];
