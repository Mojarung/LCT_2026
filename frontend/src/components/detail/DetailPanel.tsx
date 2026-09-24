import { useEffect, useRef } from 'react';

import type { QualityJson, Rule } from '../../api/artifacts';
import { useOverflowMark } from '../../hooks/useOverflowMark';
import { KIND_RU, VERDICT_RU } from '../../lib/checks';
import { meters } from '../../lib/format';
import type { MapItem } from '../../map/types';
import { useEngine } from '../../state/engine';
import { useWorkspace } from '../../state/workspace';
import { ChecksBlock } from './ChecksBlock';
import { Composition } from './Composition';
import { QualityBlock } from './QualityBlock';
import { SpeciesBlock } from './SpeciesBlock';
import { BarrierBlock, ValueBlock } from './ValueBlock';

interface DetailProps {
  placements: readonly MapItem[];
  rules: Record<string, Rule>;
  quality: QualityJson | undefined;
}

/** Перенос без перетаскивания (WCAG 2.2, 2.5.7): кнопка включает ожидание, следующий клик по
 *  карте становится новым местом. Имя кнопки не меняется с состоянием, меняется aria-pressed,
 *  а что делать дальше - говорит строка под ней. */
function MoveByClick({ item }: { item: MapItem }) {
  const placing = useWorkspace((s) => s.placing);
  const engine = useEngine();
  return (
    <div className="detail-move">
      <button
        type="button"
        className="ghost small"
        aria-pressed={placing}
        onClick={() => {
          if (placing) engine.current?.cancelPlacing();
          else engine.current?.armPlacing();
        }}
      >
        Указать новое место на карте
      </button>
      {placing ? (
        <p className="hint">
          Кликните точку на карте: посадка № {item.number} переедет туда. Повторное нажатие кнопки
          или Esc на карте отменяет.
        </p>
      ) : null}
    </div>
  );
}

function PlacementDetail({ item, rules }: { item: MapItem; rules: Record<string, Rule> }) {
  const select = useWorkspace((s) => s.select);
  const editing = useWorkspace((s) => s.editing);
  const kind = KIND_RU[item.planting_type] ?? '';
  const title =
    item.kind === 'placement'
      ? `№ ${String(item.number)}. ${item.species_ru || 'вид не назначен'}`
      : `Отказ № ${String(item.number)}`;
  return (
    <>
      <p className="detail-note">
        <button
          type="button"
          className="linkish"
          onClick={() => {
            select(null);
          }}
        >
          к составу плана
        </button>
      </p>
      <h2 className="detail-name">{title}</h2>
      {item.species_lat ? <p className="detail-lat">{item.species_lat}</p> : null}
      <span className={`verdict verdict-${item.verdict}`}>
        {VERDICT_RU[item.verdict] ?? item.verdict}
      </span>
      <p className="hint mono">
        {kind ? `${kind}, ` : ''}x {meters(item.x)}, y {meters(item.y)}
      </p>
      {editing && item.kind === 'placement' ? <MoveByClick item={item} /> : null}
      {item.note ? <p className="detail-explain">{item.note}</p> : null}
      <ValueBlock value={item.value} />
      <BarrierBlock item={item} />
      <ChecksBlock checks={item.checks} rules={rules} />
      <SpeciesBlock assortment={item.assortment} />
      {item.explanation ? (
        <details className="detail-full">
          <summary>Объяснение целиком, как в выгрузке</summary>
          <p className="detail-explain">{item.explanation}</p>
        </details>
      ) : null}
    </>
  );
}

/** Правая панель: без выбора - качество и состав плана (первый вопрос эксперта «что
 *  посажено»), с выбором - норма, по которой стоит посадка или отказ. */
export function DetailPanel({ placements, rules, quality }: DetailProps) {
  const selected = useWorkspace((s) => s.selected);
  // Отметка изменяемая: после переноса у неё новый вердикт и проверки.
  useWorkspace((s) => s.revision);
  const scrollRef = useOverflowMark<HTMLDivElement>();
  const previous = useRef<MapItem | null>(null);

  useEffect(() => {
    if (previous.current !== selected && scrollRef.current) scrollRef.current.scrollTop = 0;
    previous.current = selected;
  }, [selected, scrollRef]);

  return (
    <div className="detail-scroll" ref={scrollRef}>
      {selected ? (
        <PlacementDetail item={selected} rules={rules} />
      ) : (
        <>
          <QualityBlock quality={quality} />
          <Composition placements={placements} />
        </>
      )}
    </div>
  );
}
