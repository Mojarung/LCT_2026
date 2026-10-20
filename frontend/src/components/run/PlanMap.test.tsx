import { render, screen } from '@testing-library/react';
import { describe, expect, it, type Mock, vi } from 'vitest';

import type { PlanEngine } from '../../map/engine';
import type { EngineHooks, MapItem } from '../../map/types';
import { EngineContext } from '../../state/engine';
import { PlanMap } from './PlanMap';

// Движок карты рисует на canvas, которого в jsdom нет: его проверяют тесты src/map. Здесь -
// что холст создаёт ровно один движок, отдаёт ему события страницы и снимает его при уходе.
const created: { hooks: EngineHooks; destroy: ReturnType<typeof vi.fn> }[] = [];
vi.mock('../../map/engine', () => ({
  PlanEngine: class {
    destroy = vi.fn();
    constructor(_canvas: HTMLCanvasElement, _root: HTMLElement, hooks: EngineHooks) {
      created.push({ hooks, destroy: this.destroy });
    }
  },
}));

const item = { id: 'p1' } as MapItem;

// Хуки - отдельные моки, а не методы интерфейса: так их можно проверять без привязки this.
type HookMocks = { [K in keyof EngineHooks]: Mock<EngineHooks[K]> };

function hooks(): HookMocks {
  return {
    select: vi.fn<EngineHooks['select']>(),
    probe: vi.fn<EngineHooks['probe']>(),
    move: vi.fn<EngineHooks['move']>(),
    remove: vi.fn<EngineHooks['remove']>(),
    viewChanged: vi.fn<EngineHooks['viewChanged']>(),
    placingChanged: vi.fn<EngineHooks['placingChanged']>(),
    ambiguous: vi.fn<EngineHooks['ambiguous']>(),
  };
}

function mount(interactive: boolean, page: { current: EngineHooks }) {
  const engine = { current: null as PlanEngine | null };
  const root = { current: document.body };
  const view = render(
    <EngineContext.Provider value={engine}>
      <PlanMap root={root} hooks={page} interactive={interactive} />
    </EngineContext.Provider>,
  );
  return { ...view, engine };
}

describe('холст карты', () => {
  it('создаёт движок и передаёт ему события через текущие хуки страницы', () => {
    created.length = 0;
    const first = hooks();
    const page = { current: first };
    const { engine } = mount(true, page);
    expect(created).toHaveLength(1);
    expect(engine.current).not.toBeNull();
    const canvas = screen.getByLabelText(/План посадок на подоснове чертежа/);
    expect(canvas).toHaveAttribute('tabindex', '0');

    // Страница подменяет хуки на каждой отрисовке: движок зовёт уже новые.
    const next = hooks();
    page.current = next;
    const sent = created[0]?.hooks;
    sent?.select(item);
    sent?.probe(item, 1, 2);
    sent?.move(item, 3, 4, { x: 0, y: 0 });
    sent?.remove(item);
    sent?.viewChanged();
    sent?.placingChanged(true);
    sent?.ambiguous([item], 5, 6);
    expect(first.select).not.toHaveBeenCalled();
    expect(next.select).toHaveBeenCalledWith(item);
    expect(next.probe).toHaveBeenCalledWith(item, 1, 2);
    expect(next.move).toHaveBeenCalledWith(item, 3, 4, { x: 0, y: 0 });
    expect(next.remove).toHaveBeenCalledWith(item);
    expect(next.viewChanged).toHaveBeenCalled();
    expect(next.placingChanged).toHaveBeenCalledWith(true);
    expect(next.ambiguous).toHaveBeenCalledWith([item], 5, 6);
  });

  it('при уходе со страницы движок снимается и ссылка на него очищается', () => {
    created.length = 0;
    const { engine, unmount } = mount(false, { current: hooks() });
    expect(screen.getByLabelText(/План посадок/)).toHaveAttribute('tabindex', '-1');
    unmount();
    expect(created[0]?.destroy).toHaveBeenCalledTimes(1);
    expect(engine.current).toBeNull();
  });
});
