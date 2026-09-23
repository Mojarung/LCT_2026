import { useEffect, useRef } from 'react';

import type { QualityJson, Rule } from '../../api/artifacts';
import { useOverflowMark } from '../../hooks/useOverflowMark';
import { KIND_RU, VERDICT_RU } from '../../lib/checks';
import { meters } from '../../lib/format';
import type { MapItem } from '../../map/types';
import { useWorkspace } from '../../state/workspace';
import { ChecksBlock } from './ChecksBlock';
import { Composition } from './Composition';
import { QualityBlock } from './QualityBlock';
import { BarrierBlock, ValueBlock } from './ValueBlock';

interface DetailProps {
  placements: readonly MapItem[];
  rules: Record<string, Rule>;
  quality: QualityJson | undefined;
}

function PlacementDetail({ item, rules }: { item: MapItem; rules: Record<string, Rule> }) {
  const select = useWorkspace((s) => s.select);
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
      {item.note ? <p className="detail-explain">{item.note}</p> : null}
      <ValueBlock value={item.value} />
      <BarrierBlock item={item} />
      <ChecksBlock checks={item.checks} rules={rules} />
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
