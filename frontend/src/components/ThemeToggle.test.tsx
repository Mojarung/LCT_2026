import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { ThemeToggle } from './ThemeToggle';

const root = document.documentElement;

afterEach(() => {
  root.style.removeProperty('--is-dark');
  root.style.removeProperty('--ground');
  for (const meta of document.head.querySelectorAll('meta[name="theme-color"]')) meta.remove();
});

describe('переключатель темы', () => {
  it('из светлой переводит в тёмную, красит строку браузера и запоминает выбор', async () => {
    const meta = document.createElement('meta');
    meta.name = 'theme-color';
    meta.content = '#ffffff';
    document.head.append(meta);
    root.style.setProperty('--ground', '#1c1d1a');
    render(<ThemeToggle />);
    await userEvent.click(screen.getByRole('button', { name: 'Переключить тему' }));
    expect(root.dataset.theme).toBe('dark');
    expect(localStorage.getItem('green-theme')).toBe('dark');
    expect(meta.content).toBe('#1c1d1a');
  });

  it('тему читает по действующему эффекту: при тёмной системной кнопка ведёт в светлую', async () => {
    root.style.setProperty('--is-dark', '1');
    render(<ThemeToggle />);
    await userEvent.click(screen.getByRole('button', { name: 'Переключить тему' }));
    expect(root.dataset.theme).toBe('light');
    expect(localStorage.getItem('green-theme')).toBe('light');
  });

  it('в приватном режиме тема всё равно переключается', async () => {
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('QuotaExceededError');
    });
    render(<ThemeToggle />);
    await userEvent.click(screen.getByRole('button', { name: 'Переключить тему' }));
    expect(root.dataset.theme).toBe('dark');
  });
});
