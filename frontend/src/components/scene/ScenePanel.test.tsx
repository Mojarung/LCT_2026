import { act, fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { DEFAULT_SETTINGS, type ViewSettings } from '../../scene3d/engine';
import { ScenePanel } from './ScenePanel';

/** Пульт с настоящим состоянием: как на странице, правка возвращается в settings. */
function Harness({
  initial = {},
  onChange,
  onSpeed,
  speed = 10,
}: {
  initial?: Partial<ViewSettings>;
  onChange: (patch: Partial<ViewSettings>) => void;
  onSpeed: (speed: number) => void;
  speed?: number;
}) {
  const [settings, setSettings] = useState<ViewSettings>({ ...DEFAULT_SETTINGS, ...initial });
  return (
    <ScenePanel
      settings={settings}
      speed={speed}
      onSpeed={onSpeed}
      onChange={(patch) => {
        onChange(patch);
        setSettings((s) => ({ ...s, ...patch }));
      }}
    />
  );
}

function view(props: { initial?: Partial<ViewSettings>; speed?: number } = {}) {
  const onChange = vi.fn<(patch: Partial<ViewSettings>) => void>();
  const onSpeed = vi.fn<(speed: number) => void>();
  render(<Harness {...props} onChange={onChange} onSpeed={onSpeed} />);
  return { onChange, onSpeed, panel: screen.getByRole('complementary', { name: 'Пульт 3D-вида' }) };
}

const summaryOf = (title: string) =>
  screen.getByText(title).closest('summary')?.querySelector('.section-summary')?.textContent;

afterEach(() => {
  vi.useRealTimers();
});

describe('пульт 3D-вида', () => {
  it('сводки разделов показывают текущие значения', () => {
    view({ speed: 12.4 });
    expect(summaryOf('Посадки')).toBe('10 лет, с существующими');
    expect(summaryOf('Время и сезон')).toBe('11:00, лето');
    expect(summaryOf('Слои плана')).toBe('выключены');
    expect(summaryOf('Камера и качество')).toBe('12 м/с, обычно');
    expect(summaryOf('Окружение')).toBe('люди 40%, машины, обстановка');
    expect(summaryOf('Погода')).toBe('облачно 30%, ветер 30%');
  });

  it('сводки при включённых слоях, осадках и пустом окружении', () => {
    view({
      initial: {
        utilities: true,
        boundary: true,
        rain: 0.5,
        snow: 0.25,
        leaves: 0.1,
        people: 0,
        cars: false,
        extras: false,
        city: true,
        showExisting: false,
      },
    });
    expect(summaryOf('Слои плана')).toBe('сети, граница');
    expect(summaryOf('Погода')).toBe('дождь 50%, снег 25%, листопад 10%');
    expect(summaryOf('Окружение')).toBe('город');
    expect(summaryOf('Посадки')).toBe('10 лет');
  });

  it('пустое окружение так и называется', () => {
    view({ initial: { people: 0, cars: false, extras: false, city: false } });
    expect(summaryOf('Окружение')).toBe('пусто');
  });

  it('возраст, сезон и качество - радиокнопки', async () => {
    const user = userEvent.setup();
    const { onChange } = view();
    await user.click(screen.getByRole('radio', { name: 'взрослые' }));
    expect(onChange).toHaveBeenLastCalledWith({ age: 60 });
    expect(screen.getByRole('radio', { name: 'взрослые' })).toHaveAttribute('aria-checked', 'true');
    await user.click(screen.getByRole('radio', { name: 'осень' }));
    expect(onChange).toHaveBeenLastCalledWith({ season: 'autumn' });
    expect(summaryOf('Время и сезон')).toBe('11:00, осень');
    await user.click(screen.getByRole('radio', { name: 'быстро' }));
    expect(onChange).toHaveBeenLastCalledWith({ quality: 'low' });
    // На «быстро» объёмный свет недоступен.
    expect(screen.getByRole('checkbox', { name: 'Объёмный свет и сглаживание' })).toBeDisabled();
  });

  it('галочки слоёв и окружения', async () => {
    const user = userEvent.setup();
    const { onChange } = view();
    const cases: [RegExp, Partial<ViewSettings>][] = [
      [/Существующие насаждения/, { showExisting: false }],
      [/Подземные сети/, { utilities: true }],
      [/Граница работ/, { boundary: true }],
      [/Объёмный свет/, { enhanced: false }],
      [/Машины у бортов/, { cars: false }],
      [/Скамейки, урны/, { extras: false }],
      [/Город вокруг съёмки/, { city: true }],
    ];
    for (const [name, patch] of cases) {
      await user.click(screen.getByRole('checkbox', { name }));
      expect(onChange).toHaveBeenLastCalledWith(patch);
    }
  });

  it('ползунки: время, поворот солнца, облачность, погода, люди, скорость', () => {
    const { onChange, onSpeed } = view();
    const slide = (label: RegExp, value: string) => {
      fireEvent.change(screen.getByLabelText(label), { target: { value } });
    };
    slide(/Время суток/, '18.5');
    expect(onChange).toHaveBeenLastCalledWith({ hour: 18.5 });
    slide(/Поворот солнца/, '45');
    expect(onChange).toHaveBeenLastCalledWith({ sunTurn: 45 });
    expect(screen.getByText('+45°')).toBeInTheDocument();
    slide(/Поворот солнца/, '-30');
    expect(screen.getByText('-30°')).toBeInTheDocument();
    slide(/Облачность/, '0.6');
    expect(onChange).toHaveBeenLastCalledWith({ clouds: 0.6 });
    slide(/Люди на тротуарах/, '0.8');
    expect(onChange).toHaveBeenLastCalledWith({ people: 0.8 });
    slide(/^Ветер/, '0.5');
    expect(onChange).toHaveBeenLastCalledWith({ wind: 0.5 });
    slide(/^Дождь/, '0.2');
    expect(onChange).toHaveBeenLastCalledWith({ rain: 0.2 });
    slide(/^Снег/, '0.1');
    expect(onChange).toHaveBeenLastCalledWith({ snow: 0.1 });
    slide(/^Листопад/, '0.3');
    expect(onChange).toHaveBeenLastCalledWith({ leaves: 0.3 });
    expect(screen.getByLabelText(/^Листопад/)).toHaveValue('0.3');
    slide(/Скорость полёта/, '0');
    expect(onSpeed).toHaveBeenLastCalledWith(expect.closeTo(1, 5));
    expect(screen.getByLabelText(/Скорость полёта/)).toHaveAttribute(
      'aria-valuetext',
      '10 метров в секунду',
    );
  });

  it('мягкий вечерний свет ставит час показа и лёгкую облачность', async () => {
    const user = userEvent.setup();
    const { onChange } = view();
    await user.click(screen.getByRole('button', { name: 'Поставить мягкий вечерний свет' }));
    const patch = onChange.mock.lastCall?.[0];
    expect(patch?.clouds).toBe(0.2);
    expect(patch?.hour).toBeGreaterThan(12);
  });

  it('прокрутка суток двигает час по таймеру и останавливается', () => {
    vi.useFakeTimers();
    const { onChange } = view({ initial: { hour: 23.95 } });
    const spin = screen.getByRole('button', { name: 'Прокрутить сутки' });
    fireEvent.click(spin);
    expect(spin).toHaveAttribute('aria-pressed', 'true');
    act(() => {
      vi.advanceTimersByTime(100);
    });
    // Через полночь - снова с нуля.
    expect(onChange).toHaveBeenLastCalledWith({ hour: 0.05 });
    act(() => {
      vi.advanceTimersByTime(100);
    });
    expect(onChange).toHaveBeenLastCalledWith({ hour: 0.15 });
    fireEvent.click(screen.getByRole('button', { name: 'Остановить сутки' }));
    const calls = onChange.mock.calls.length;
    act(() => {
      vi.advanceTimersByTime(500);
    });
    expect(onChange).toHaveBeenCalledTimes(calls);
  });

  it('раздел помнит, открыт он или свёрнут', () => {
    view();
    const weather = screen.getByText('Погода').closest('details') as HTMLDetailsElement;
    expect(weather.open).toBe(false);
    weather.open = true;
    fireEvent(weather, new Event('toggle'));
    expect(JSON.parse(localStorage.getItem('green-scene-sections-v2') ?? '{}')).toEqual({
      weather: true,
    });
  });

  it('испорченное хранилище не ломает пульт', () => {
    localStorage.setItem('green-scene-sections-v2', '{не json');
    view();
    expect(screen.getByText('Посадки').closest('details')).toHaveAttribute('open');
  });

  it('пульт сворачивается к правому краю', async () => {
    const user = userEvent.setup();
    const { panel } = view();
    await user.click(within(panel).getByRole('button', { name: 'Свернуть пульт' }));
    expect(panel).toHaveClass('collapsed');
    expect(within(panel).queryByText('Посадки')).not.toBeInTheDocument();
    await user.click(within(panel).getByRole('button', { name: 'Развернуть пульт' }));
    expect(within(panel).getByText('Посадки')).toBeInTheDocument();
  });
});
