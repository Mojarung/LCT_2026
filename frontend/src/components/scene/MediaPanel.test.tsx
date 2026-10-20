import { act, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { PhotoOut } from '../../api/types';
import { mediaItems, type Shot } from '../../lib/media';
import { MediaPanel, type MediaPanelProps } from './MediaPanel';

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

function view(props: Partial<MediaPanelProps> & { shots?: Shot[] } = {}) {
  const photos = props.photos ?? [];
  const handlers = {
    onScenery: vi.fn(),
    onModern: vi.fn(),
    onPrompt: vi.fn(),
    onToggle: vi.fn(),
    onShotScale: vi.fn(),
    onShot: vi.fn(),
    onPhotoView: vi.fn(),
    onShots: vi.fn(),
    onRemoveShot: vi.fn(),
    onDeletePhoto: vi.fn(),
    onPhoto: vi.fn(),
    onOpen: vi.fn(),
  };
  const utils = render(
    <MediaPanel
      items={mediaItems(props.shots ?? [], photos)}
      photos={photos}
      available
      reason={null}
      scenery={false}
      modern
      customPrompt={false}
      collapsed={false}
      shotScale={1}
      shooting={false}
      sending={false}
      photoBusy={0}
      {...handlers}
      {...props}
    />,
  );
  return { ...utils, ...handlers, panel: screen.getByRole('region', { name: 'Снимки и фото' }) };
}

afterEach(() => {
  vi.useRealTimers();
});

describe('панель «Снимки и фото»', () => {
  it('пустая панель подсказывает, что здесь будет', () => {
    view();
    expect(screen.getByText(/Здесь соберутся снимки и фото нейросетью/)).toBeInTheDocument();
    expect(screen.getByText('0', { selector: '.media-count' })).toBeInTheDocument();
  });

  it('три способа снять и настройки к ним', async () => {
    const user = userEvent.setup();
    const h = view();
    await user.click(screen.getByRole('button', { name: /^Кадры/ }));
    expect(h.onShots).toHaveBeenCalled();
    await user.click(screen.getByRole('button', { name: /^Снимок/ }));
    expect(h.onShot).toHaveBeenCalled();
    await user.click(screen.getByRole('button', { name: /^Фото ИИ/ }));
    expect(h.onPhotoView).toHaveBeenCalled();
    await user.click(screen.getByRole('button', { name: 'крупнее ×2' }));
    expect(h.onShotScale).toHaveBeenCalledWith(2);
    await user.click(screen.getByRole('button', { name: 'фон и деревья' }));
    expect(h.onScenery).toHaveBeenCalledWith(true);
    await user.click(screen.getByRole('button', { name: 'новые фасады' }));
    expect(h.onModern).toHaveBeenCalledWith(false);
    await user.click(screen.getByRole('button', { name: 'промпт' }));
    expect(h.onPrompt).toHaveBeenCalled();
    await user.click(screen.getByRole('button', { name: 'Свернуть снимки и фото' }));
    expect(h.onToggle).toHaveBeenCalled();
  });

  it('снимок ×2, свой промпт, фото в работе и отправка вида', async () => {
    const user = userEvent.setup();
    const h = view({ shotScale: 2, customPrompt: true, photoBusy: 2, sending: true });
    expect(screen.getByRole('button', { name: /^Снимок ×2/ })).toHaveAttribute(
      'title',
      'Снимок кадра в PNG, вдвое крупнее. Клавиша P',
    );
    expect(screen.getByRole('button', { name: 'крупнее ×2' })).toHaveAttribute(
      'aria-pressed',
      'true',
    );
    await user.click(screen.getByRole('button', { name: 'крупнее ×2' }));
    expect(h.onShotScale).toHaveBeenCalledWith(1);
    expect(screen.getByRole('button', { name: 'свой промпт' })).toHaveAttribute(
      'data-custom',
      'true',
    );
    const photoButton = screen.getByRole('button', { name: /^Фото ИИ · 2/ });
    expect(photoButton).toBeDisabled();
    expect(photoButton.querySelector('.spin')).not.toBeNull();
  });

  it('без модели - причина и нет настроек фото', () => {
    view({ available: false, reason: null, shooting: true });
    expect(screen.getByText('Фото нейросетью недоступно: не настроено.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^Фото ИИ/ })).toHaveAttribute(
      'title',
      'Фото недоступно: не настроено. Клавиша F',
    );
    expect(screen.queryByRole('button', { name: 'промпт' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^Снимок/ })).toBeDisabled();
  });

  it('свёрнутая панель показывает число элементов на кнопке', () => {
    const { panel } = view({ collapsed: true, shots: [shot()] });
    expect(panel).toHaveClass('collapsed');
    expect(
      within(panel).getByRole('button', { name: 'Развернуть снимки и фото' }),
    ).toHaveTextContent('1');
  });

  it('карточка снимка: открыть, скачать, удалить, в фото ИИ', async () => {
    const user = userEvent.setup();
    const s = shot();
    const h = view({ shots: [s] });
    const card = screen.getByRole('listitem');
    expect(within(card).getByText('1920×1080')).toBeInTheDocument();
    expect(within(card).getByText('снимок')).toBeInTheDocument();
    expect(within(card).getByRole('link', { name: 'скачать' })).toHaveAttribute('download', s.name);
    await user.click(within(card).getByRole('button', { name: 'открыть' }));
    expect(h.onOpen).toHaveBeenCalledWith(0);
    await user.click(within(card).getByTitle('Открыть крупно'));
    expect(h.onOpen).toHaveBeenCalledTimes(2);
    await user.click(within(card).getByRole('button', { name: 'удалить' }));
    expect(h.onRemoveShot).toHaveBeenCalledWith(s.id);
    await user.click(within(card).getByRole('button', { name: 'в фото ИИ' }));
    expect(h.onPhoto).toHaveBeenCalledWith(s);
  });

  it('готовое фото: превью без апскейла, время, скачать и удалить', async () => {
    const user = userEvent.setup();
    const h = view({ photos: [photo({ scenery: true })] });
    const card = screen.getByRole('listitem');
    expect(within(card).getByRole('img', { name: 'Кадры улицы. Сверху' })).toHaveAttribute(
      'src',
      '/raw.jpg',
    );
    expect(within(card).getByText('ИИ + фон')).toBeInTheDocument();
    expect(within(card).getByText('готово за 85 с')).toBeInTheDocument();
    expect(within(card).getByRole('link', { name: 'скачать' })).toHaveAttribute(
      'download',
      'p1.jpg',
    );
    expect(within(card).queryByRole('button', { name: 'в фото ИИ' })).not.toBeInTheDocument();
    await user.click(within(card).getByRole('button', { name: 'удалить' }));
    expect(h.onDeletePhoto).toHaveBeenCalledWith('p1');
  });

  it('фото без времени и без отдельного превью', () => {
    view({ photos: [photo({ seconds: null, raw_url: null })] });
    expect(screen.getByText('готово')).toBeInTheDocument();
    expect(screen.getByRole('img')).toHaveAttribute('src', '/frame.png');
  });

  it('фото с ошибкой помечено красным и без скачивания', () => {
    view({ photos: [photo({ state: 'failed', photo_url: null, error: 'oom' })] });
    const card = screen.getByRole('listitem');
    expect(within(card).getByText('ошибка')).toHaveAttribute('data-bad', 'true');
    expect(within(card).getByText('не получилось, можно повторить')).toHaveClass('bad');
    expect(within(card).queryByRole('link', { name: 'скачать' })).not.toBeInTheDocument();
    expect(within(card).getByRole('img')).toHaveAttribute('src', '/frame.png');
  });

  it('фото в работе: полоса хода двигается раз в секунду, удалить нельзя', () => {
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval', 'Date'] });
    vi.setSystemTime(Date.parse('2026-10-20T10:00:25Z'));
    const running = photo({
      id: 'r',
      state: 'running',
      started_at: '2026-10-20T10:00:05Z',
      photo_url: null,
    });
    const queued = photo({ id: 'q', state: 'queued', created_at: '2026-10-20T10:00:10Z' });
    const done = photo({ id: 'd', seconds: 100, created_at: '2026-10-20T09:00:00Z' });
    view({ photos: [running, queued, done] });
    const cards = screen.getAllByRole('listitem');
    const runningCard = cards.find((c) => c.textContent.includes('модель рисует')) as HTMLElement;
    expect(runningCard).toHaveAttribute('data-pending', 'true');
    expect(within(runningCard).getByText('модель рисует, осталось около 80 с')).toBeVisible();
    expect(within(runningCard).getByRole('button', { name: 'удалить' })).toBeDisabled();
    expect(within(runningCard).getByRole('button', { name: 'удалить' })).toHaveAttribute(
      'title',
      'Фото ещё рисуется',
    );
    const bar = runningCard.querySelector<HTMLElement>('.media-progress span');
    expect(bar?.style.width).toBe('20%');
    act(() => {
      vi.advanceTimersByTime(10_000);
    });
    expect(within(runningCard).getByText('модель рисует, осталось около 70 с')).toBeVisible();
    expect(screen.getByText('в очереди, перед ним 1')).toBeInTheDocument();
  });
});
