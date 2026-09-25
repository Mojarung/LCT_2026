import './styles/fonts.css';
import './styles/tokens.css';
import './styles/base.css';
import './styles/console.css';
import './styles/workspace.css';
import './styles/detail.css';
import './styles/responsive.css';

import { QueryClientProvider } from '@tanstack/react-query';
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { createBrowserRouter, RouterProvider } from 'react-router';

import { makeQueryClient } from './api/queryClient';
import { routes } from './router';

const container = document.getElementById('root');
if (!container) throw new Error('В index.html нет #root');

const router = createBrowserRouter(routes);
const client = makeQueryClient();

createRoot(container).render(
  <StrictMode>
    <QueryClientProvider client={client}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </StrictMode>,
);
