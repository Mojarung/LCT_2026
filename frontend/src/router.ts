import type { RouteObject } from 'react-router';

import { Layout } from './components/Layout';
import { ConsolePage } from './pages/ConsolePage';
import { ModelsPage } from './pages/ModelsPage';
import { NotFoundPage } from './pages/NotFoundPage';
import { RunPage } from './pages/RunPage';

/** Два рабочих экрана - консоль запуска и рабочее место прогона - и справочная база моделей
 *  растений. Остальные адреса - API и /docs, их отдаёт сервер, а не приложение. */
export const routes: RouteObject[] = [
  {
    path: '/',
    Component: Layout,
    children: [
      { index: true, Component: ConsolePage },
      { path: 'runs/:runId', Component: RunPage },
      { path: 'models', Component: ModelsPage },
      { path: '*', Component: NotFoundPage },
    ],
  },
];
