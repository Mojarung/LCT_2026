import { describe, expect, it, vi } from 'vitest';

import type { PlacementJson, PlanJson, RejectionJson, SpeciesBrief } from '../api/artifacts';
import { installCanvas, installImaging } from '../test/canvas';
import { loadSurface, toMapItems } from './items';

const placement = (over: Partial<PlacementJson> = {}): PlacementJson => ({
  id: 'p1',
  number: 1,
  planting_type: 'tree',
  species: null,
  x: 10,
  y: 20,
  verdict: 'allowed',
  notes: [],
  explanation: 'по норме',
  assortment: null,
  value: null,
  checks: [],
  ...over,
});

const rejection = (over: Partial<RejectionJson> = {}): RejectionJson => ({
  id: 'r1',
  number: 2,
  planting_type: 'tree',
  x: 1,
  y: 2,
  verdict: 'rejected',
  note: 'кабель',
  barrier_m: 1.5,
  explanation: 'ближе 2 м',
  blocking: [
    {
      rule_id: 'R-CABLE',
      outcome: 'fail',
      measured_m: 1,
      threshold_m: 2,
      object_class: 'utility.power_cable',
    },
  ],
  ...over,
});

const plan = (placements: PlacementJson[], rejections: RejectionJson[]): PlanJson => ({
  run_id: 'run',
  source: { name: 'a.dxf', sha256: '', dxf_version: 'AC1032' },
  summary: {},
  placements,
  rejections,
  warnings: [],
});

describe('данные прогона в отметки карты', () => {
  it('посадка с видом: радиус - половина кроны, имя и код вида', () => {
    const species: SpeciesBrief = {
      code: 'tilia_cordata',
      name_ru: 'Липа мелколистная',
      name_lat: 'Tilia cordata',
      crown_diameter_m: 8,
      life_form: 'tree',
    };
    const { placements } = toMapItems(plan([placement({ species })], []));
    expect(placements[0]).toMatchObject({
      kind: 'placement',
      id: 'p1',
      x: 10,
      y: 20,
      radius: 4,
      species_code: 'tilia_cordata',
      species_ru: 'Липа мелколистная',
      species_lat: 'Tilia cordata',
      explanation: 'по норме',
    });
  });

  it('посадка без вида - крона 3 м, отказ - метка 1,2 м с проверками блокировки', () => {
    const { placements, rejections } = toMapItems(plan([placement()], [rejection()]));
    expect(placements[0]?.radius).toBe(1.5);
    expect(placements[0]?.species_code).toBeUndefined();
    expect(rejections[0]).toMatchObject({
      kind: 'rejection',
      radius: 1.2,
      note: 'кабель',
      barrier_m: 1.5,
      value: null,
    });
    expect(rejections[0]?.checks[0]?.rule_id).toBe('R-CABLE');
  });
});

class GoodImage {
  src = '';
  naturalWidth = 2;
  naturalHeight = 1;
  decode(): Promise<void> {
    return Promise.resolve();
  }
}

class BrokenImage extends GoodImage {
  override decode(): Promise<void> {
    return Promise.reject(new Error('битый PNG'));
  }
}

describe('карта покрытий', () => {
  it('растр из артефакта прогона ложится на клетки чертежа, маски грунта и покрытия готовы', async () => {
    installCanvas();
    installImaging();
    const created: GoodImage[] = [];
    vi.stubGlobal(
      'Image',
      class extends GoodImage {
        constructor() {
          super();
          created.push(this);
        }
      },
    );
    const surface = await loadSurface('run 1', {
      origin: [100, 200],
      cell_m: 0.5,
      width: 40,
      height: 30,
    });
    expect(created[0]?.src).toBe('/api/v1/runs/run%201/artifacts/surface.png');
    expect(surface).toMatchObject({ x: 100, y: 200, w: 20, h: 15 });
    expect(surface?.img).toBe(created[0]);
    expect(surface?.soil).toBeInstanceOf(HTMLCanvasElement);
    expect(surface?.paved).toBeInstanceOf(HTMLCanvasElement);
  });

  it('PNG не декодировался - карты покрытий нет', async () => {
    vi.stubGlobal('Image', BrokenImage);
    await expect(
      loadSurface('run', { origin: [0, 0], cell_m: 1, width: 1, height: 1 }),
    ).resolves.toBeNull();
  });

  it('без контекста холста растр есть, а масок нет', async () => {
    vi.stubGlobal('Image', GoodImage);
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null);
    const surface = await loadSurface('run', { origin: [0, 0], cell_m: 1, width: 1, height: 1 });
    expect(surface).toMatchObject({ soil: null, paved: null });
  });
});
