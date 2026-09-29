/* Свёрнута ли панель 3D-вида: у каждой панели свой ключ в браузере. */

import { useState } from 'react';

/** Свёрнута ли панель: запоминается в браузере, без хранилища - развёрнута. */
export function useSideCollapsed(key: string): [boolean, () => void] {
  const [collapsed, setCollapsed] = useState(() => {
    try {
      return localStorage.getItem(key) === '1';
    } catch {
      return false;
    }
  });
  const toggle = () => {
    setCollapsed((v) => {
      try {
        localStorage.setItem(key, v ? '0' : '1');
      } catch {
        /* без хранилища панель просто не запомнит состояние */
      }
      return !v;
    });
  };
  return [collapsed, toggle];
}
