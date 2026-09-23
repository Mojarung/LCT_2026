import type { RouteObject } from 'react-router';

import { Layout } from './components/Layout';
import { ConsolePage } from './pages/ConsolePage';
import { NotFoundPage } from './pages/NotFoundPage';
import { RunPage } from './pages/RunPage';

/** Два экрана: консоль запуска и рабочее место прогона. Остальные адреса - API и /docs,
 *  их отдаёт сервер, а не приложение. */
export const routes: RouteObject[] = [
  {
    path: '/',
    Component: Layout,
    children: [
      { index: true, Component: ConsolePage },
      { path: 'runs/:runId', Component: RunPage },
      { path: '*', Component: NotFoundPage },
    ],
  },
];
