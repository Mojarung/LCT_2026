import { screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { renderApp } from './test/render';

describe('приложение', () => {
  it('монтируется с переходом к содержимому и переключателем темы', async () => {
    renderApp('/');

    expect(await screen.findByRole('link', { name: 'К содержимому' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Переключить тему' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Документация API' })).toHaveAttribute('href', '/docs');
  });

  it('неизвестный адрес показывает страницу «не найдено», а не пустой экран', async () => {
    renderApp('/нет-такой-страницы');

    expect(await screen.findByRole('heading', { name: 'Такой страницы нет' })).toBeInTheDocument();
  });
});
