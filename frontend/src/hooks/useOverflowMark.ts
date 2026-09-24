import { useEffect, useRef } from 'react';

/** Пометить прокручиваемую панель, у которой содержимое не помещается. Без пометки
 *  переполнение молчаливое: на высоте 720 панель прячет полторы сотни пикселей ровной кромкой,
 *  и это читается как «здесь всё». Растушёвку снизу по data-overflow рисует CSS; data-scrolled
 *  - прокручено от начала: тогда текст растворяется и у верхней кромки, а не идёт под значок
 *  сворачивания панели. */
export function useOverflowMark<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  useEffect(() => {
    const element = ref.current;
    if (!element) return;
    const mark = () => {
      element.dataset.overflow = element.scrollHeight - element.clientHeight > 4 ? '1' : '0';
      element.dataset.scrolled = element.scrollTop > 2 ? '1' : '0';
    };
    mark();
    element.addEventListener('scroll', mark, { passive: true });
    const resize = new ResizeObserver(mark);
    resize.observe(element);
    const content = new MutationObserver(mark);
    content.observe(element, { childList: true, subtree: true, characterData: true });
    return () => {
      element.removeEventListener('scroll', mark);
      resize.disconnect();
      content.disconnect();
    };
  }, []);
  return ref;
}
