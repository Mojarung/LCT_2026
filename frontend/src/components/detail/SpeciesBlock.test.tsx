import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import type { Assortment } from '../../api/artifacts';
import { SpeciesBlock } from './SpeciesBlock';

const reason = (kind: string, text: string, rule_id: string | null = null) => ({
  kind,
  text,
  rule_id,
  source: null,
  condition: null,
});

const assortment: Assortment = {
  status: 'assigned',
  percent: 74,
  factors: {},
  structure: { id: 'row-57', kind: 'row' },
  reasons: [
    reason('pilot', 'применён в 2 паспортах пилота'),
    reason('norm', 'рекомендован для категории «улицы и дороги»', 'R-MGSN-CATEGORY-001'),
    reason('reference', 'морозостойкость зоны 4'),
    reason('norm', 'до теплосети 9.0 м при норме 4.0 м', 'R-HEAT-TREE-003'),
    reason('norm', 'до края тротуара 2.0 м при норме 2.0 м', 'R-THORNSW-TREE-001'),
    reason('norm', 'не аллерген', 'R-ALLERGEN-001'),
  ],
  alternatives: [
    { code: 'acer_ginnala', name_ru: 'Клён Гиннала', percent: 45, why_not: 'оценка ниже' },
    { code: 'betula', name_ru: 'Берёза повислая', percent: 60, why_not: 'массовый аллерген' },
  ],
};

describe('SpeciesBlock', () => {
  it('leads with suitability and the norms that chose the species', () => {
    render(<SpeciesBlock assortment={assortment} />);

    expect(screen.getByRole('heading', { name: 'Почему этот вид' })).toBeVisible();
    expect(screen.getByText('74%')).toBeVisible();
    const shown = within(screen.getByRole('list', { name: 'Основания выбора вида' }));
    const items = shown.getAllByRole('listitem').map((li) => li.textContent);
    // Нормы идут первыми и с номером правила, справочник и пилот - после.
    expect(items[0]).toContain('рекомендован для категории «улицы и дороги»');
    expect(items[0]).toContain('R-MGSN-CATEGORY-001');
    expect(items).toHaveLength(3);
    expect(screen.getByText('Ещё 3 основания')).toBeInTheDocument();
  });

  it('names the runners-up and says why not only when it is not just a lower score', () => {
    render(<SpeciesBlock assortment={assortment} />);

    const runners = screen.getByText(/Альтернативы/);
    expect(runners).toHaveTextContent('Клён Гиннала 45%');
    expect(runners).toHaveTextContent('Берёза повислая 60%: массовый аллерген');
    expect(runners).not.toHaveTextContent('оценка ниже');
  });

  it('renders nothing without selection data', () => {
    const { container } = render(<SpeciesBlock assortment={null} />);
    expect(container).toBeEmptyDOMElement();
  });
});
