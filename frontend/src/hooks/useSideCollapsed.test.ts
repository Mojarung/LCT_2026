import { act, renderHook } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { useSideCollapsed } from './useSideCollapsed';

describe('свёрнутая панель 3D-вида', () => {
  it('по умолчанию развёрнута, переключение запоминается в браузере', () => {
    const { result } = renderHook(() => useSideCollapsed('green-scene-test'));
    expect(result.current[0]).toBe(false);
    act(() => {
      result.current[1]();
    });
    expect(result.current[0]).toBe(true);
    expect(localStorage.getItem('green-scene-test')).toBe('1');
    act(() => {
      result.current[1]();
    });
    expect(result.current[0]).toBe(false);
    expect(localStorage.getItem('green-scene-test')).toBe('0');
  });

  it('читает сохранённое состояние своей панели', () => {
    localStorage.setItem('green-scene-test', '1');
    expect(renderHook(() => useSideCollapsed('green-scene-test')).result.current[0]).toBe(true);
    expect(renderHook(() => useSideCollapsed('green-scene-other')).result.current[0]).toBe(false);
  });

  it('без хранилища браузера панель развёрнута и всё равно сворачивается', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('SecurityError');
    });
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('SecurityError');
    });
    const { result } = renderHook(() => useSideCollapsed('green-scene-test'));
    expect(result.current[0]).toBe(false);
    act(() => {
      result.current[1]();
    });
    expect(result.current[0]).toBe(true);
  });
});
