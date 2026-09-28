import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import type { Rule, RuleCheck } from '../../api/artifacts';
import { ChecksBlock } from './ChecksBlock';

const rule = (rule_id: string, act_short: string, clause: string): Rule => ({
  rule_id,
  object_class: 'utility.heat',
  min_distance_m: 2,
  measure_to: 'wall',
  severity: 'forbidden',
  act_id: act_short,
  act_title: act_short,
  act_short,
  act_edition: '',
  url: '',
  clause,
  quote: '',
  status: 'verified',
  related: [],
});

const heat = (rule_id: string): RuleCheck => ({
  rule_id,
  outcome: 'pass',
  measured_m: 2.23,
  threshold_m: 2,
  object_class: 'utility.heat',
});

describe('ChecksBlock', () => {
  it('два правила на один замер до одного объекта - одна строка и оба основания', () => {
    const rules = {
      'R-HEAT-TREE-001': rule('R-HEAT-TREE-001', 'СП 42.13330.2016', 'п. 9.6, табл. 9.1'),
      'R-HEAT-TREE-002': rule('R-HEAT-TREE-002', '623-ПП', 'п. 4.2.8'),
    };
    render(
      <ChecksBlock checks={[heat('R-HEAT-TREE-001'), heat('R-HEAT-TREE-002')]} rules={rules} />,
    );
    // Жюри по дизайну (итерация 8): «до теплосети 2,23 м» стояло дважды и читалось как два объекта.
    expect(screen.getAllByText('до теплосети')).toHaveLength(1);
    expect(screen.getByText('R-HEAT-TREE-001')).toBeInTheDocument();
    expect(screen.getByText('R-HEAT-TREE-002')).toBeInTheDocument();
    expect(screen.getByText(/623-ПП, п\. 4\.2\.8/)).toBeInTheDocument();
  });
});
