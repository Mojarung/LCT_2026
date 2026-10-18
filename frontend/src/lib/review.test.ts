import { describe, expect, it } from 'vitest';

import { REPORT, REVIEW } from './__fixtures__/review';
import {
  ASSIGNABLE,
  boundsOf,
  evidenceName,
  groupMembers,
  groupOrder,
  groupNeedsReview,
  relatedIndices,
  reviewJson,
  selectedIndices,
  selectedLabel,
  unresolvedCount,
} from './review';

describe('уточнение объектов: разбор', () => {
  it('запасные классы требуют уточнения, подтверждённое препятствие — нет', () => {
    const original = REPORT.groups[0];
    if (!original) throw new Error('Нет группы в тестовом отчёте');
    const assumed = {
      ...original,
      object_class: 'obstacle',
      evidence: { method: 'symbol_assumed:1072KR' },
    };
    expect(groupNeedsReview(assumed)).toBe(true);
    expect(groupNeedsReview({ ...assumed, evidence: { method: 'explicit_feature' } })).toBe(false);
    expect(groupNeedsReview({ ...assumed, review_reason: null })).toBe(false);
    const report = { ...REPORT, groups: [assumed, ...REPORT.groups.slice(1)] };
    expect(unresolvedCount(REVIEW, {}, report)).toBe(2);
    expect(unresolvedCount(REVIEW, { 'f:1': 'obstacle' }, report)).toBe(1);
  });

  it('штрихи одной выноски выбираются вместе', () => {
    const data = {
      ...REVIEW,
      callouts: [
        {
          source_refs: ['f:1', 'f:3'],
          label_ref: 'l:1',
          text: 'каб. кол.',
          certain: false,
          reason: 'неоднозначность',
        },
      ],
    };
    expect(relatedIndices(data, [0])).toEqual([0, 2]);
    expect(relatedIndices(data, [1])).toEqual([1]);
  });
  it('объекты раскладываются по группам отчёта', () => {
    expect(groupMembers(REVIEW, 3)).toEqual([[0, 2], [1], [3]]);
  });

  it('неизвестные группы идут первыми, остальные сохраняют порядок', () => {
    // Опоры первыми, неизвестная линия второй, газон третьим.
    const groups = [...REPORT.groups];
    groups.unshift(...groups.splice(1, 1));
    expect(groupOrder({ ...REPORT, groups })).toEqual([1, 0, 2]);
  });

  it('номер объекта: 0 - вся группа, N - N-й, пусто и мимо - ничего', () => {
    const members = [0, 2];
    expect(selectedIndices(members, '0')).toEqual([0, 2]);
    expect(selectedIndices(members, '2')).toEqual([2]);
    expect(selectedIndices(members, '')).toEqual([]);
    expect(selectedIndices(members, ' ')).toEqual([]);
    expect(selectedIndices(members, '3')).toEqual([]);
    expect(selectedIndices(members, '1.5')).toEqual([]);
  });

  it('подпись выбирается по номеру на карте с единицы', () => {
    expect(selectedLabel(REVIEW, '2')?.id).toBe('l:2');
    expect(selectedLabel(REVIEW, '0')).toBeNull();
    expect(selectedLabel(REVIEW, '5')).toBeNull();
  });

  it('габарит выбранного - по границам объектов, пустой выбор - единичный квадрат', () => {
    expect(boundsOf(REVIEW, [0, 2])).toEqual([0, 0, 20, 12]);
    expect(boundsOf(REVIEW, [])).toEqual([0, 0, 1, 1]);
  });

  it('неуточнённые считаются с учётом назначений человека', () => {
    expect(unresolvedCount(REVIEW, {})).toBe(2);
    expect(unresolvedCount(REVIEW, { 'f:1': 'curb' })).toBe(1);
  });

  it('назначить можно любой класс, кроме неизвестных', () => {
    expect(ASSIGNABLE).toContain('curb');
    expect(ASSIGNABLE).toContain('contour');
    expect(ASSIGNABLE).not.toContain('unknown');
    expect(ASSIGNABLE).not.toContain('utility.unknown');
  });

  it('основание называется словами, в том числе составное', () => {
    expect(evidenceName('unmatched')).toBe('имя не распознано');
    expect(evidenceName('inferred_surface:газон')).toBe('выведено по слову «газон» в имени');
    expect(evidenceName('assumed_geometry:sheet_frame')).toBe('замена по геометрии: рамка листа');
    expect(evidenceName('symbol_geometry:KOLOD')).toBe('условный знак KOLOD');
    expect(evidenceName('callout_leader:12345678:00000000:pipe_a')).toBe(
      'выноска к сети, оформление',
    );
    expect(evidenceName('sheet_furniture:Условные обозначения')).toBe(
      'оформление листа рядом с «Условные обозначения»',
    );
    expect(evidenceName('sheet_furniture:text_strokes')).toBe(
      'оформление листа: текст, разобранный на штрихи',
    );
    expect(evidenceName('something_new')).toBe('something_new');
    expect(evidenceName(undefined)).toBe('не уточнено');
  });
});

describe('уточнение объектов: JSON повторного прогона', () => {
  const overrides = {
    spacing_m: 6,
    layer_classes: { '0': 'curb' },
    block_classes: { B: 'pole' },
    feature_classes: { old: 'fence' },
    label_roles: { old: 'soil' },
  };

  it('как у тиммейта: точные ссылки вместо широких назначений, хеш и строгий прогон', () => {
    const text = reviewJson(overrides, REVIEW, REPORT, { 'f:1': 'curb' }, { 'l:1': 'ignore' });
    expect(text.endsWith('\n')).toBe(true);
    const values = JSON.parse(text) as Record<string, unknown>;
    expect(values).toEqual({
      spacing_m: 6,
      // f:2 уточнён раньше (explicit_layer) - сохраняется; f:1 - назначение человека.
      feature_classes: { 'f:2': 'pole', 'f:1': 'curb' },
      // l:2 уточнена раньше (explicit_label), l:1 - назначение человека.
      label_roles: { 'l:2': 'paved', 'l:1': 'ignore' },
      semantic_source_sha256: 'abc123',
      require_known_objects: true,
      require_reviewed_objects: true,
    });
  });

  it('назначение человека перекрывает прежнее уточнение того же объекта', () => {
    const values = JSON.parse(reviewJson({}, REVIEW, REPORT, { 'f:2': 'structure' }, {})) as {
      feature_classes: Record<string, string>;
    };
    expect(values.feature_classes['f:2']).toBe('structure');
  });
});
