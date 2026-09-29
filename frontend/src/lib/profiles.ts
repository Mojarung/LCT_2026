/** Профили норм по-русски. Имя профиля (strict, barriers...) - ключ API, CLI и файла
 *  config/profiles/<имя>.yaml; человеку показывается название и одна фраза, для чего профиль.
 *  Порядок записей - порядок в списке формы: основной режим первым. Тест сверяет словарь с
 *  файлами config/profiles, чтобы новый профиль не появился в форме латиницей. */
export const PROFILES: Record<string, { title: string; text: string }> = {
  strict: {
    title: 'Строгий',
    text: 'Основной режим. Там, где на чертеже нет данных о подземных сетях, посадка не ставится.',
  },
  no_utilities: {
    title: 'Без данных о сетях',
    text: 'Для чертежа без подземных сетей, например выгрузки АСУ ОДХ. Посадки ставятся с пометкой «требует согласования».',
  },
  barriers: {
    title: 'С прикорневыми барьерами',
    text: 'Строгий режим, но дерево можно поставить ближе табличного отступа к сетям и борту, если в яме будет барьер (СП 42.13330, табл. 9.1, прим. 5).',
  },
  shrubs: {
    title: 'Кустарник вдоль борта',
    text: 'Только кустарник: рядовая посадка вдоль борта, без деревьев.',
  },
  review: {
    title: 'Проверка чертежа',
    text: 'Показывает, как сервис прочитал чертёж: незнакомые обозначения не угадываются по имени слоя, а выносятся на уточнение.',
  },
};

export function profileTitle(name: string): string {
  return PROFILES[name]?.title ?? name;
}

/** Профили в порядке словаря; неизвестные сервису новые - в конце, своим именем. */
export function orderProfiles(names: readonly string[]): string[] {
  const known = Object.keys(PROFILES);
  const rank = (name: string) => {
    const index = known.indexOf(name);
    return index === -1 ? known.length : index;
  };
  return [...names].sort((a, b) => rank(a) - rank(b) || a.localeCompare(b));
}
