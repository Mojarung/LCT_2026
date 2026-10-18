/** Лоадер «змейка»: семь квадратов в повёрнутой сетке 3 x 3 по очереди сдвигаются в пустую
 *  клетку. Перенос animated-loader-1 (21st.dev, avanishverma4) в стек проекта: без Tailwind и
 *  своей кнопки темы, цвет - из токенов, движение - transform вместо left/top, чтобы браузер
 *  не пересчитывал раскладку каждый кадр. */
export function SquareLoader({ size = 64, label }: { size?: number; label?: string }) {
  return (
    <span
      className="square-loader"
      style={{ ['--loader-size' as string]: `${String(size)}px` }}
      role={label ? 'img' : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
    >
      {Array.from({ length: 7 }, (_, i) => (
        <i key={i} style={{ ['--i' as string]: String(i) }} />
      ))}
    </span>
  );
}
