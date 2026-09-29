import { describe, expect, it } from 'vitest';

import catalog from '../../../config/species.yaml?raw';
import raw from './templateSigns.json?raw';
import {
  EXISTING_SIGNS,
  SPECIES_SIGNS,
  speciesSign,
  type TemplateSignFile,
  templateSignOf,
  setTemplateSignFile,
  signColor,
  WITHOUT_TEMPLATE_SIGN,
} from './templateSigns';

const file = JSON.parse(raw) as TemplateSignFile;
const names = new Set(file.signs.map((sign) => sign.name));

/** Коды видов каталога прямо из config/species.yaml: соответствие обязано идти за ним. */
function catalogCodes(): string[] {
  return [...catalog.matchAll(/\{code: ([a-z_]+),/g)].map((match) => match[1] ?? '');
}

describe('соответствие видов каталога знакам шаблона заказчика', () => {
  it('каждый вид каталога либо со знаком шаблона, либо явно в списке «без знака»', () => {
    const codes = catalogCodes();
    const mapped = codes.filter((code) => code in SPECIES_SIGNS);
    const without = codes.filter((code) => WITHOUT_TEMPLATE_SIGN.includes(code));
    expect(codes).toHaveLength(55);
    expect(mapped.length + without.length).toBe(55);
    expect(mapped.filter((code) => without.includes(code))).toEqual([]);
  });

  it('в таблице нет кодов, которых нет в каталоге', () => {
    const codes = new Set(catalogCodes());
    const listed = [...Object.keys(SPECIES_SIGNS), ...WITHOUT_TEMPLATE_SIGN];
    expect(listed.filter((code) => !codes.has(code))).toEqual([]);
    expect(new Set(listed).size).toBe(listed.length);
  });

  it('каждый знак из таблицы соответствия есть в данных шаблона', () => {
    const signs = new Set(Object.values(SPECIES_SIGNS).map(([sign]) => sign));
    expect([...signs].filter((sign) => !names.has(sign))).toEqual([]);
    expect(Object.values(EXISTING_SIGNS).filter((sign) => !names.has(sign))).toEqual([]);
  });

  it('род берёт знак рода, вид со своей строкой - свой знак', () => {
    expect(SPECIES_SIGNS.tilia_cordata).toEqual(['Липа', 'род']);
    expect(SPECIES_SIGNS.tilia_platyphyllos).toEqual(['Липа', 'род']);
    expect(SPECIES_SIGNS.acer_negundo).toEqual(['Клен', 'род']);
    expect(SPECIES_SIGNS.lonicera_tatarica).toEqual(['Жимолость', 'род']);
    expect(SPECIES_SIGNS.pinus_sylvestris).toEqual(['Сосна', 'род']);
    // «Сосна горная» - своя строка шаблона, а не общий знак сосны.
    expect(SPECIES_SIGNS.pinus_mugo).toEqual(['Сосна горная', 'вид']);
    // Черёмуха в каталоге - Prunus, но в шаблоне у неё своя строка, как в русском названии.
    expect(SPECIES_SIGNS.prunus_padus?.[0]).toBe('Черемуха');
    // Ясеня, маакии и скумпии в шаблоне нет: общий знак, а не чужой.
    expect(WITHOUT_TEMPLATE_SIGN).toEqual(
      expect.arrayContaining(['fraxinus_excelsior', 'maackia_amurensis', 'cotinus_coggygria']),
    );
  });
});

describe('данные знаков из шаблона', () => {
  it('шапка называет источник, команду генерации и дату', () => {
    expect(file.source).toContain('Шаблоны значков.dwg');
    expect(file.command).toContain('tools/extract_template_signs.py');
    expect(file.generated).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    expect(file.hash).toMatch(/^[0-9a-f]{32}$/);
  });

  it('все строки таблицы шаблона со знаком: 64 вида и 4 существующих насаждения', () => {
    const bySection = (section: string) => file.signs.filter((s) => s.section === section).length;
    expect(bySection('conifer')).toBe(11);
    expect(bySection('tree')).toBe(18);
    expect(bySection('shrub')).toBe(31);
    expect(bySection('liana')).toBe(5);
    expect(bySection('existing')).toBe(4);
  });

  it('пути - только M, L, Z и числа в пределах знака', () => {
    for (const sign of file.signs) {
      expect(sign.paths.length).toBeGreaterThan(0);
      for (const [kind, color, alpha, weight, d] of sign.paths) {
        expect(['f', 's']).toContain(kind);
        expect(color).toMatch(/^(ink|#[0-9a-f]{6})$/);
        expect(alpha).toBeGreaterThan(0);
        expect(alpha).toBeLessThanOrEqual(1);
        expect(weight).toBeGreaterThanOrEqual(0);
        expect(d).toMatch(/^M[-\d. MLZ]+$/);
        const numbers = d.match(/-?\d*\.?\d+/g)?.map(Number) ?? [];
        expect(Math.max(...numbers.map(Math.abs))).toBeLessThanOrEqual(1.25);
      }
      expect(sign.tone[0]).toMatch(/^(ink|#[0-9a-f]{6})$/);
    }
  });
});

describe('выбор знака', () => {
  it('без загруженных данных знака шаблона нет: карта рисует общий знак', () => {
    expect(speciesSign('tilia_cordata')).toBeUndefined();
  });

  it('после загрузки вид получает знак своей строки, вид без знака - ничего', () => {
    setTemplateSignFile(file);
    expect(speciesSign('tilia_platyphyllos')?.name).toBe('Липа');
    expect(speciesSign('pinus_mugo')?.name).toBe('Сосна горная');
    expect(speciesSign('fraxinus_excelsior')).toBeUndefined();
    expect(speciesSign(undefined)).toBeUndefined();
    expect(templateSignOf(EXISTING_SIGNS.conifer)?.section).toBe('existing');
  });
});

describe('цвета знака в теме', () => {
  const light = {
    ink: '#141414',
    paper: '#ffffff',
    crown: '',
    coniferCrown: '',
    coniferRing: '',
    halo: '',
  };
  const dark = { ...light, ink: '#ecebe6', paper: '#16191d' };
  const lum = (css: string) => {
    const [r = 0, g = 0, b = 0] = (css.match(/\d+/g) ?? []).map(Number);
    return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255;
  };

  it('на светлом листе - цвета чертежа, ACI 7 - чернила', () => {
    expect(signColor('ink', light)).toBe('#141414');
    expect(signColor('#134c00', light)).toBe('#134c00');
    expect(signColor('#fefefe', light)).toBe('#fefefe');
  });

  it('в тёмной теме тёмные цвета светлеют с тем же оттенком, белая маска - цвет листа', () => {
    expect(signColor('ink', dark)).toBe('#ecebe6');
    expect(signColor('#fefefe', dark)).toBe('#16191d');
    const green = signColor('#134c00', dark);
    expect(lum(green)).toBeGreaterThanOrEqual(0.49);
    const [r = 0, g = 0, b = 0] = (green.match(/\d+/g) ?? []).map(Number);
    expect(g).toBeGreaterThan(r);
    expect(g).toBeGreaterThan(b);
    // Светлый цвет чертежа не трогается.
    expect(signColor('#bbedbb', dark)).toBe('#bbedbb');
  });
});
