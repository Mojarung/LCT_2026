import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeAll, describe, expect, it, vi } from 'vitest';

import type { PhotoOut } from '../../api/types';
import { type GalleryShot, ShotGallery, type ShotGalleryProps } from './ShotGallery';

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

function shot(patch: Partial<GalleryShot> = {}): GalleryShot {
  return {
    key: 'k1',
    pose: { x: 0, y: 30, z: 0, yaw: 0, pitch: -0.5 },
    viewpoint: 'aerial',
    label: 'Сверху',
    trees: ['Tilia cordata'],
    shrubs: ['Spiraea japonica'],
    names: ['Липа мелколистная', 'Спирея японская'],
    mark: { u: 0.25, v: 0.75 },
    url: 'blob:k1',
    blob: new Blob(['png']),
    ...patch,
  };
}

function view(props: Partial<ShotGalleryProps> = {}) {
  const handlers = {
    onScenery: vi.fn<(value: boolean) => void>(),
    onPhoto: vi.fn<(s: GalleryShot) => void>(),
    onOpen: vi.fn<(s: GalleryShot) => void>(),
    onClose: vi.fn<() => void>(),
  };
  const utils = render(
    <ShotGallery
      title="Кадры улицы"
      shots={[shot()]}
      busy={false}
      error={null}
      photos={[]}
      requested={{}}
      available
      reason={null}
      scenery={false}
      {...handlers}
      {...props}
    />,
  );
  return { ...utils, ...handlers, dialog: screen.getByRole('dialog', { name: 'Кадры улицы' }) };
}

describe('галерея кадров', () => {
  it('открывается модально с фокусом на заголовке и показывает кадр с метками', () => {
    const { dialog } = view();
    expect(dialog).toHaveAttribute('open');
    expect(screen.getByRole('heading', { name: 'Кадры улицы' })).toHaveFocus();
    expect(screen.getByRole('img', { name: 'Кадры улицы. Сверху' })).toHaveAttribute(
      'src',
      'blob:k1',
    );
    expect(dialog.querySelector('.gallery-mark')).toHaveStyle({ left: '25%', top: '75%' });
    expect(screen.getByText('Липа мелколистная, Спирея японская')).toHaveAttribute(
      'title',
      'Tilia cordata, Spiraea japonica',
    );
    expect(screen.getByRole('link', { name: 'PNG' })).toHaveAttribute('download', 'k1.png');
  });

  it('кнопки кадра: в 3D, фото; переход к улице и закрытие', async () => {
    const user = userEvent.setup();
    const onStreet = vi.fn();
    const { onOpen, onPhoto, onClose } = view({ onStreet });
    await user.click(screen.getByRole('button', { name: 'в 3D' }));
    expect(onOpen).toHaveBeenCalledWith(expect.objectContaining({ key: 'k1' }));
    await user.click(screen.getByRole('button', { name: 'фото' }));
    expect(onPhoto).toHaveBeenCalledWith(expect.objectContaining({ key: 'k1' }));
    await user.click(screen.getByRole('button', { name: 'кадры улицы' }));
    expect(onStreet).toHaveBeenCalled();
    await user.click(screen.getByRole('button', { name: 'к 3D-виду · Esc' }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('Esc (событие cancel) закрывает галерею через страницу, а не сам диалог', () => {
    const { dialog, onClose } = view();
    const cancel = new Event('cancel', { cancelable: true });
    dialog.dispatchEvent(cancel);
    expect(cancel.defaultPrevented).toBe(true);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('галочка фона и деревьев', async () => {
    const user = userEvent.setup();
    const { onScenery } = view();
    await user.click(screen.getByRole('checkbox', { name: 'Дорисовать фон и деревья' }));
    expect(onScenery).toHaveBeenCalledWith(true);
  });

  it('без модели фото - причина вместо галочки и кнопки фото', () => {
    view({ available: false, reason: 'нет видеокарты' });
    expect(screen.getByText('Фото недоступно: нет видеокарты.')).toBeInTheDocument();
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'фото' })).not.toBeInTheDocument();
  });

  it('без причины - общая формулировка', () => {
    view({ available: false, reason: null });
    expect(
      screen.getByText('Фото недоступно: генерация на сервере не настроена.'),
    ).toBeInTheDocument();
  });

  it('пока кадры снимаются - «Снимаю кадры…», переход к улице заблокирован; ошибка видна', () => {
    view({ shots: [], busy: true, onStreet: vi.fn(), error: 'В сцене нет посадок.' });
    expect(screen.getByText('Снимаю кадры…')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'кадры улицы' })).toBeDisabled();
    expect(screen.getByText('В сцене нет посадок.')).toBeInTheDocument();
  });

  it('заказанное фото: очередь, работа, готово, ошибка с подробностями', () => {
    const { rerender } = view({
      requested: { k1: 'p1' },
      photos: [photo({ state: 'queued', photo_url: null })],
    });
    expect(screen.getByText('в очереди')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'ещё фото' })).toBeDisabled();
    const props = {
      title: 'Кадры улицы',
      shots: [shot()],
      busy: false,
      error: null,
      requested: { k1: 'p1' },
      available: true,
      reason: null,
      scenery: false,
      onScenery: vi.fn(),
      onPhoto: vi.fn(),
      onOpen: vi.fn(),
      onClose: vi.fn(),
    };
    rerender(<ShotGallery {...props} photos={[photo({ state: 'running', photo_url: null })]} />);
    expect(screen.getByText('модель рисует, около 1,5 мин')).toBeInTheDocument();
    rerender(<ShotGallery {...props} photos={[photo({ upscaled: true, scenery: true })]} />);
    expect(screen.getByRole('button', { name: 'ещё фото' })).toBeEnabled();
    const figure = screen.getByRole('figure');
    expect(within(figure).getByRole('img', { name: 'Фото: Сверху' })).toHaveAttribute(
      'src',
      '/raw.jpg',
    );
    expect(within(figure).getByText(/с фоном и деревьями/)).toBeInTheDocument();
    expect(within(figure).getByRole('link', { name: '6144×3456 ↗' })).toHaveAttribute(
      'href',
      '/photo.jpg',
    );
    rerender(
      <ShotGallery
        {...props}
        photos={[photo({ state: 'failed', photo_url: null, error: 'sd-cli: out of memory' })]}
      />,
    );
    expect(screen.getByText('Фото не получилось: можно заказать ещё раз.')).toBeInTheDocument();
    expect(screen.getByText('Подробности')).toBeInTheDocument();
    expect(screen.getByText('sd-cli: out of memory')).toBeInTheDocument();
    rerender(<ShotGallery {...props} photos={[photo({ state: 'failed', photo_url: null })]} />);
    expect(screen.queryByText('Подробности')).not.toBeInTheDocument();
  });

  it('прежние фото прогона: только готовые, по одному на кадр, не больше шести', () => {
    const earlier = [
      photo({ id: 'a', shot: 'Кадр А', raw_url: null }),
      photo({ id: 'a2', shot: 'Кадр А' }),
      photo({ id: 'b', shot: 'Кадр А', scenery: true }),
      photo({ id: 'c', shot: '' }),
      photo({ id: 'q', shot: 'Кадр Q', state: 'queued' }),
      ...['1', '2', '3', '4', '5'].map((n) => photo({ id: `n${n}`, shot: `Кадр ${n}` })),
      photo({ id: 'mine', shot: 'Мой' }),
    ];
    view({ photos: earlier, requested: { other: 'mine' } });
    expect(screen.getByRole('heading', { name: 'Прежние фото прогона' })).toBeInTheDocument();
    const list = screen.getAllByRole('list')[1] as HTMLElement;
    const cards = within(list).getAllByRole('listitem');
    expect(cards).toHaveLength(6);
    expect(within(cards[0] as HTMLElement).getByRole('img')).toHaveAttribute('src', '/photo.jpg');
    expect(within(list).getByRole('img', { name: 'Фото: прежнее фото прогона' })).toBeVisible();
    expect(within(list).queryByText('Кадр Q')).not.toBeInTheDocument();
    expect(within(list).queryByText('Мой')).not.toBeInTheDocument();
  });

  it('при закрытии компонента диалог закрывается', () => {
    const { dialog, unmount } = view();
    unmount();
    expect(dialog).not.toHaveAttribute('open');
  });
});
