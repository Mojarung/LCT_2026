import type { TreeClearanceConflict } from '../../scene3d/treeClearance';

const metres = (n: number) => n.toLocaleString('ru-RU', { maximumFractionDigits: 2 });

export function TreeClearanceNotice({ conflict }: { conflict: TreeClearanceConflict }) {
  return (
    <div className="scene-tree-clearance">
      <strong>Недостаточный отступ до здания</strong>
      <p>
        По модели: от ствола до здания <b>{metres(conflict.distance)} м</b>, требование для новой
        посадки — не менее <b>{metres(conflict.required)} м</b>.
      </p>
      <p>
        Дерево уже было в исходном чертеже. Это не новая посадка сервиса; статус вырубки здесь не
        определён.
      </p>
      <span>
        {conflict.rule.act_short}, {conflict.rule.clause}
      </span>
    </div>
  );
}
