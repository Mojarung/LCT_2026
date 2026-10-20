import { act, fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeAll, describe, expect, it, vi } from 'vitest';

import type { PhotoOut } from '../../api/types';
import { mediaItems, type Shot } from '../../lib/media';
import { MediaViewer } from './MediaViewer';

// jsdom не открывает <dialog> модально: открытие - атрибутом open, как у браузера.
beforeAll(() => {
  HTMLDialogElement.prototype.showModal = function () {
    this.setAttribute('open', '');
  };
  HTMLDialogElement.prototype.close = function () {
    this.removeAttribute('open');
  };
});

function photo(patch: Partial<PhotoOut> = {}): PhotoOut {
  return {
    id: 'p1',
    state: 'succeeded',
    scenery: false,
    season: 'summer',
    hour: 11,
    viewpoint: 'aerial',
    species: [],
    shrubs: [],
    shot: 'Кадры улицы. Сверху',
    modern: true,
    custom: false,
    width: 1536,
    height: 864,
    created_at: '2026-10-20T10:00:00Z',
    started_at: '2026-10-20T10:00:05Z',
    finished_at: '2026-10-20T10:01:30Z',
    seconds: 84.6,
    error: null,
    upscaled: false,
    source_url: '/frame.png',
    photo_url: '/photo.jpg',
    raw_url: '/raw.jpg',
    ...patch,
  };
}

function shot(patch: Partial<Shot> = {}): Shot {
  return {
    id: Date.parse('2026-10-20T12:00:00Z'),
    url: 'blob:shot-1',
    name: '3d-street-20261020-120000.png',
    width: 1920,
    height: 1080,
    blob: new Blob(['png']),
    viewpoint: 'aerial',
    trees: ['Tilia cordata'],
    shrubs: [],
    ...patch,
  };
}

function view(
  props: Partial<Parameters<typeof MediaViewer>[0]> & { shots?: Shot[]; photos?: PhotoOut[] },
) {
  const shots = props.shots ?? [];
  const photos = props.photos ?? [];
  const onIndex = vi.fn();
  const onClose = vi.fn();
  const items = props.items ?? mediaItems(shots, photos);
  const utils = render(
    <MediaViewer
      items={items}
      index={props.index ?? 0}
      photos={photos}
      onIndex={props.onIndex ?? onIndex}
      onClose={props.onClose ?? onClose}
      onPhoto={props.onPhoto}
    />,
  );
  return { ...utils, onIndex, onClose, items };
}

describe('MediaViewer', () => {
  it('показывает снимок крупно, даёт скачать его и отправить в нейросеть', async () => {
    const onPhoto = vi.fn();
    const s = shot();
    view({ shots: [s], onPhoto });
    const dialog = screen.getByRole('dialog');
    expect(dialog).toHaveAttribute('open');
    expect(screen.getByText(/Снимок 3D-вида, 1920×1080/)).toBeInTheDocument();
    expect(screen.getByText('1 / 1')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'скачать' })).toHaveAttribute(
      'download',
      '3d-street-20261020-120000.png',
    );
    // Один элемент - листать некуда.
    expect(screen.getByRole('button', { name: 'Предыдущий' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Следующий' })).toBeDisabled();
    await userEvent.click(screen.getByRole('button', { name: 'в фото ИИ' }));
    expect(onPhoto).toHaveBeenCalledWith(s);
  });

  it('без нейросети у снимка нет кнопки «в фото ИИ»', () => {
    view({ shots: [shot()] });
    expect(screen.queryByRole('button', { name: 'в фото ИИ' })).not.toBeInTheDocument();
  });

  it('у готового фото переключает фото и 3D-кадр, по которому его нарисовали', async () => {
    view({ photos: [photo({ upscaled: true, scenery: true })] });
    const img = screen.getByRole('img');
    expect(img).toHaveAttribute('src', '/photo.jpg');
    expect(screen.getByText(/с фоном и деревьями, 6144×3456, 85 с/)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'оригинал ↗' })).toHaveAttribute('href', '/photo.jpg');
    expect(screen.getByRole('link', { name: 'скачать' })).toHaveAttribute('download', 'p1.jpg');
    expect(screen.getByRole('radio', { name: 'фото' })).toHaveAttribute('aria-checked', 'true');

    await userEvent.click(screen.getByRole('radio', { name: '3D-кадр' }));
    expect(screen.getByRole('img')).toHaveAttribute('src', '/frame.png');
    expect(screen.getByRole('radio', { name: '3D-кадр' })).toHaveAttribute('aria-checked', 'true');
  });

  it('фото в работе показывает кадр и ход очереди, без скачивания', () => {
    const queued = photo({
      id: 'p2',
      state: 'queued',
      photo_url: null,
      created_at: '2026-10-20T10:05:00Z',
    });
    const running = photo({ id: 'p1', state: 'running', photo_url: null, seconds: null });
    view({ photos: [queued, running], items: mediaItems([], [queued]) });
    expect(screen.getByText(/Кадр, который рисует модель/)).toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent('в очереди, перед ним 1');
    expect(screen.getByRole('img')).toHaveAttribute('src', '/frame.png');
    expect(screen.queryByRole('link', { name: 'скачать' })).not.toBeInTheDocument();
    expect(screen.queryByRole('radiogroup')).not.toBeInTheDocument();
  });

  it('листает стрелками на экране и с клавиатуры по кругу', async () => {
    const shots = [
      shot({ id: 3000, url: 'blob:a' }),
      shot({ id: 2000, url: 'blob:b' }),
      shot({ id: 1000, url: 'blob:c' }),
    ];
    const { onIndex } = view({ shots, index: 0 });
    expect(screen.getByText('1 / 3')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Следующий' }));
    expect(onIndex).toHaveBeenLastCalledWith(1);
    await userEvent.click(screen.getByRole('button', { name: 'Предыдущий' }));
    // С первого назад - на последний.
    expect(onIndex).toHaveBeenLastCalledWith(2);

    const dialog = screen.getByRole('dialog');
    fireEvent.keyDown(dialog, { key: 'ArrowRight' });
    expect(onIndex).toHaveBeenLastCalledWith(1);
    fireEvent.keyDown(dialog, { key: 'ArrowLeft' });
    expect(onIndex).toHaveBeenLastCalledWith(2);
    onIndex.mockClear();
    fireEvent.keyDown(dialog, { key: 'Enter' });
    expect(onIndex).not.toHaveBeenCalled();
  });

  it('закрывается кнопкой и по Esc, а при размонтировании закрывает окно', async () => {
    const { onClose, unmount } = view({ shots: [shot()] });
    await userEvent.click(screen.getByRole('button', { name: 'закрыть · Esc' }));
    expect(onClose).toHaveBeenCalledTimes(1);
    const dialog = screen.getByRole('dialog');
    const cancel = new Event('cancel', { cancelable: true });
    dialog.dispatchEvent(cancel);
    expect(cancel.defaultPrevented).toBe(true);
    expect(onClose).toHaveBeenCalledTimes(2);
    unmount();
    expect(dialog).not.toHaveAttribute('open');
  });

  it('за пределами списка ничего не рисует', () => {
    const { container } = view({ shots: [shot()], index: 5 });
    expect(container).toBeEmptyDOMElement();
  });

  it('пересчитывает ход фото раз в секунду, пока открыт просмотр', () => {
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval', 'Date'] });
    try {
      vi.setSystemTime(Date.parse('2026-10-20T10:00:15Z'));
      const running = photo({ state: 'running', photo_url: null, seconds: null });
      view({ photos: [running] });
      // Своих замеров нет - ждём 100 с, прошло 10.
      expect(screen.getByRole('status')).toHaveTextContent('осталось около 90 с');
      act(() => {
        vi.advanceTimersByTime(5000);
      });
      expect(screen.getByRole('status')).toHaveTextContent('осталось около 85 с');
    } finally {
      vi.useRealTimers();
    }
  });
});
