import { useEffect, useRef } from 'react';

/** Пометить прокручиваемую панель, у которой содержимое не помещается. Без пометки
 *  переполнение молчаливое: на высоте 720 панель прячет полторы сотни пикселей ровной кромкой,
 *  и это читается как «здесь всё». Растушёвку снизу по data-overflow рисует CSS. */
export function useOverflowMark<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  useEffect(() => {
    const element = ref.current;
    if (!element) return;
    const mark = () => {
      element.dataset.overflow = element.scrollHeight - element.clientHeight > 4 ? '1' : '0';
    };
    mark();
    const resize = new ResizeObserver(mark);
    resize.observe(element);
    const content = new MutationObserver(mark);
    content.observe(element, { childList: true, subtree: true, characterData: true });
    return () => {
      resize.disconnect();
      content.disconnect();
    };
  }, []);
  return ref;
}
