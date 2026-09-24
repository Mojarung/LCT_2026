/* Состояние рабочего места прогона: выбор, слои, фильтр видов, режим правки, панели.
 *
 * Хранилище общее для страницы и движка карты. Отметки карты (MapItem) - изменяемые объекты
 * движка: при переносе он двигает их сам, поэтому после таких изменений увеличивается
 * revision, и панели перечитывают поля выбранной посадки. */

import { create } from 'zustand';

import { DEFAULT_LAYERS, type LayerKey, type Layers, type MapItem } from '../map/types';

export interface Message {
  text: string;
  kind: 'info' | 'error';
}

interface Panels {
  /** Левая панель прогона свёрнута. */
  left: boolean;
  /** Правая панель состава свёрнута. */
  right: boolean;
  /** Панель условных обозначений открыта. */
  legend: boolean;
}

interface WorkspaceState {
  runId: string | null;
  selected: MapItem | null;
  revision: number;
  layers: Layers;
  speciesOff: ReadonlySet<string>;
  highlight: string | null;
  editing: boolean;
  /** Ждём клик по карте с новым местом выбранной посадки. */
  placing: boolean;
  stale: boolean;
  message: Message;
  panels: Panels;
  zoomShare: number;
  orientation: 'street' | 'north';

  enter: (runId: string) => void;
  select: (item: MapItem | null) => void;
  touch: () => void;
  setLayer: (key: LayerKey, on: boolean) => void;
  toggleSpecies: (code: string, visible: boolean) => void;
  showAllSpecies: () => void;
  toggleHighlight: (code: string) => void;
  setEditing: (on: boolean) => void;
  setPlacing: (on: boolean) => void;
  setStale: (stale: boolean) => void;
  say: (text: string, kind?: Message['kind']) => void;
  togglePanel: (panel: 'left' | 'right') => void;
  setLegend: (open: boolean) => void;
  setZoomShare: (share: number) => void;
  setOrientation: (orientation: 'street' | 'north') => void;
}

const read = (key: string): string | null => {
  try {
    return localStorage.getItem(key);
  } catch {
    return null; // приватный режим: состояние не переживёт перезагрузку
  }
};

const write = (key: string, value: string): void => {
  try {
    localStorage.setItem(key, value);
  } catch {
    /* приватный режим */
  }
};

/** Панели - как их оставили. Обозначения по умолчанию открыты: без них цвет на карте не значит
 *  ничего. На узком экране - закрыты: там панель накрывает половину карты. */
function savedPanels(): Panels {
  const narrow = typeof window !== 'undefined' && window.matchMedia('(max-width: 1080px)').matches;
  const legend = read('green-legend');
  return {
    left: read('green-panel-left') === '1',
    right: read('green-panel-right') === '1',
    legend: legend === null ? !narrow : legend !== '0',
  };
}

const fresh = () => ({
  selected: null,
  revision: 0,
  layers: DEFAULT_LAYERS,
  speciesOff: new Set<string>(),
  highlight: null,
  editing: false,
  placing: false,
  stale: false,
  message: { text: '', kind: 'info' as const },
  zoomShare: 0.5,
  orientation: 'street' as const,
});

export const useWorkspace = create<WorkspaceState>()((set, get) => ({
  runId: null,
  ...fresh(),
  panels: savedPanels(),

  enter(runId) {
    if (get().runId === runId) return;
    set({ runId, ...fresh(), panels: savedPanels() });
  },
  select(item) {
    set({ selected: item });
  },
  touch() {
    set((state) => ({ revision: state.revision + 1 }));
  },
  setLayer(key, on) {
    set((state) => ({ layers: { ...state.layers, [key]: on } }));
  },
  toggleSpecies(code, visible) {
    const next = new Set(get().speciesOff);
    if (visible) next.delete(code);
    else next.add(code);
    set({ speciesOff: next });
  },
  showAllSpecies() {
    set({ speciesOff: new Set() });
  },
  toggleHighlight(code) {
    set((state) => ({ highlight: state.highlight === code ? null : code }));
  },
  setEditing(on) {
    set({
      editing: on,
      message: {
        text: on
          ? 'Тяните посадку мышью или двигайте Alt со стрелками. Delete удаляет выбранную.'
          : '',
        kind: 'info',
      },
    });
  },
  setPlacing(on) {
    set({ placing: on });
  },
  setStale(stale) {
    set({ stale });
  },
  say(text, kind = 'info') {
    set({ message: { text, kind } });
  },
  togglePanel(panel) {
    const collapsed = !get().panels[panel];
    write(`green-panel-${panel}`, collapsed ? '1' : '0');
    set((state) => ({ panels: { ...state.panels, [panel]: collapsed } }));
  },
  setLegend(open) {
    write('green-legend', open ? '1' : '0');
    set((state) => ({ panels: { ...state.panels, legend: open } }));
  },
  setZoomShare(share) {
    set({ zoomShare: share });
  },
  setOrientation(orientation) {
    set({ orientation });
  },
}));

/** Для тестов: хранилище - модульное состояние, и размонтирование страницы его не чистит. */
export function resetWorkspace(): void {
  useWorkspace.setState({ runId: null, ...fresh(), panels: savedPanels() });
}
