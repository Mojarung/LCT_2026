"""Объёмы зданий для трёхмерной сцены: контур с чертежа, высота по подписям Мосгеотреста.

Геоподоснова не хранит высоту здания. Мосгеотрест пишет внутри контура отдельными текстами
материал стен (К, М, СМ), признак жилого или нежилого (Ж, Н) и число этажей; у крылец -
покрытие (А, Б, Ц), у контейнерной площадки - «М.Я.» (`docs/notes/21-slopes-and-schools.md`).
Из этого и собирается объём: основание - грань, которую замыкают линии слоёв зданий, высота -
этажность, умноженная на типовой этаж.

Контур здания на чертеже часто не одна замкнутая полилиния: стена нарисована кусками, куски
сходятся в узлах, часть контура лежит на соседнем планшете. Поэтому грани восстанавливаются по
всей линейной графике слоёв зданий сразу: концы, разошедшиеся меньше чем на 2 см, сводятся в
точку, линии разбиваются в пересечениях, polygonize собирает грани. Грань - ещё не здание:
двор внутри кольца домов тоже грань. Двор отличают по дыре исходного полигона и по признакам
открытой земли внутри (газон, тротуар, дерево, подпись грунта).

Высоты здесь - допущение для картинки, а не норма: ни один акт свода не задаёт высоту этажа,
и отступы плана от высоты зданий не зависят. Поэтому у каждой высоты записано основание
(`floors_source`), а у сцены - баланс граней: по нему видно, что потерялось и почему.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
import shapely
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from scipy.spatial import KDTree
from shapely import STRtree
from shapely.geometry import LineString

from green.application.surfaces import Material, label_material
from green.domain.objects import ObjectClass

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from numpy.typing import NDArray
    from shapely.geometry import Polygon

    from green.domain.objects import Feature, TextLabel

# Концы ближе 2 см - погрешность оцифровки, а не разрыв: так расходятся куски одной стены на
# стыке планшетов. Больший допуск начал бы замыкать пунктир частей зданий и навесов.
GAP_M = 0.02
# Грань мельче - обломок сшивки, колонна навеса (окружность) или знак, а не объём.
MIN_FACE_M2 = 2.0
# Точка вставки текста - его левый нижний угол: у маленького здания она выходит за контур
# на сантиметры. Подпись без грани вокруг достаётся ближайшей грани в пределах метра.
LABEL_REACH_M = 1.0
# Сколько общей стены нужно, чтобы грань без подписи взяла этажность соседа, и сколько общей
# границы с дырой полигона, чтобы грань считалась двором, а не зданием во дворе.
SHARED_EDGE_M = 2.0
# Грань без подписи и без признаков земли крупнее этого - скорее квартал, обведённый стенами
# соседних домов, чем здание: у самых крупных корпусов пилотных улиц подпись есть.
MAX_UNPROVEN_M2 = 2500.0
MAX_FLOORS = 60
# Съёмка Мосгеотреста режется на планшеты 1:500 по сетке 250 x 250 м, и контур дома, который
# не уместился на планшет улицы, обрывается на рамке: у Кустанайской концы открытых контуров
# лежат ровно на x = 16000, y = -5000, -5250, -5500. Конец ближе FRAME_TOL_M к линии сетки -
# это рамка, и контур замыкается её куском в пределах FRAME_REACH_M от конца: основание дома
# в сцене кончается там же, где кончается съёмка.
SHEET_M = 250.0
FRAME_TOL_M = 0.05
FRAME_REACH_M = 40.0
# Открытая цепочка, обошедшая контур с трёх сторон, замыкается хордой: так рисуют дом, у
# которого стена ушла на соседний лист не по рамке. Хорда не длиннее CHORD_M, а цепочка
# минимум в CHORD_RATIO раз длиннее хорды - прямую стену или забор хорда не замкнёт.
CHORD_M = 30.0
CHORD_RATIO = 3.0
# Штрих короче этого - пунктир частей здания и навесов (выступы над землёй, ридер разбирает
# их из блоков msdElementType*): такие линии не замыкаются, иначе на тротуаре вырастут
# козырьки и эркеры до земли.
MIN_STROKE_M = 1.5

# Высота этажа от пола до пола в московском жилье - около 3 м: 2,8 м в панельных домах,
# 3,0-3,5 м в кирпичных. 1,2 м сверху - цоколь и парапет. Одноэтажное нежилое (магазин,
# гараж, павильон) выше жилого этажа - 4 м. Это типовые величины для наглядности сцены,
# а не норма и не обмер: подпись даёт число этажей, но не их высоту.
STOREY_M = 3.0
PLINTH_AND_PARAPET_M = 1.2
ONE_STOREY_M = 4.0
# «Ж» без числа: жилой дом без подписанной этажности считаем типовой пятиэтажкой.
RESIDENTIAL_FLOORS = 5
LETTER_FLOORS = 1
# Этажность по площади основания, когда подписей нет совсем: киоск и гараж в один этаж,
# небольшое нежилое в два, остальное - пятиэтажка.
AREA_FLOORS = ((150.0, 1), (600.0, 2))
LARGE_FLOORS = 5
# Крыльцо - три ступени по 15 см; контейнерная площадка - бак с ограждением; сооружение
# (парапет, вентиляционный киоск, лестница) - метр над землёй.
PORCH_M = 0.45
CONTAINER_M = 1.5
STRUCTURE_M = 1.0

BUILDING = "building"
PORCH = "porch"
CONTAINER = "container"
STRUCTURE = "structure"
SOURCE_LABEL = "label"
SOURCE_NEIGHBOR = "neighbor"
SOURCE_LETTER = "letter"
SOURCE_ASSUMED = "assumed"
RESIDENTIAL = "residential"
NON_RESIDENTIAL = "non_residential"

WALLS = {"К": "brick", "М": "metal", "СМ": "mixed"}
USES = {"Ж": RESIDENTIAL, "Н": NON_RESIDENTIAL}
PORCH_TEXTS = frozenset({"А", "Б", "Ц"})
CONTAINER_TEXTS = frozenset({"М.Я", "МЯ"})
# Не надземный объём: фундамент, котлован, подземное сооружение, разрушенное здание.
# Рисуются низким сооружением, чтобы не взять этажность соседнего корпуса.
GROUND_TEXTS = frozenset({"ФУНД", "КОТЛОВАН", "ПОДЗ.СООР", "РАЗР"})
# Что внутри грани говорит об открытой земле: двор, а не здание.
GROUND_CLASSES = frozenset(
    {
        ObjectClass.LAWN,
        ObjectClass.SIDEWALK,
        ObjectClass.ROAD,
        ObjectClass.EXISTING_TREE,
        ObjectClass.EXISTING_SHRUB,
        ObjectClass.EXISTING_WOODLAND,
    }
)

# Тире любой длины - дефис; латинские двойники кириллицы - кириллица: чертёж набирают на
# разных раскладках, и «K-» латиницей значит то же, что «К-».
_NORMALIZE = str.maketrans(
    {
        "‒": "-",
        "–": "-",
        "—": "-",
        "―": "-",
        "−": "-",
        **dict(zip("ABCEHKMOPTX", "АВСЕНКМОРТХ", strict=True)),
    }
)
_SIGN = re.compile(r"(?P<wall>СМ|К|М)?-?(?P<use>Ж|Н)?-?(?P<floors>\d{1,2})?")
# Коды shapely.get_type_id: LineString и LinearRing, Polygon.
_LINE_TYPE_IDS = (1, 2)
_POLYGON_TYPE_ID = 3
_NO_GEOMETRY: NDArray[np.object_] = np.empty(0, dtype=object)


@dataclass(frozen=True, slots=True)
class BuildingVolume:
    """Объём для сцены: основание в координатах чертежа (метры) и высота с основанием.

    floors_source: label - число этажей подписано внутри; neighbor - взято у подписанной
    части того же здания с общей стеной от 2 м; letter - по букве без числа (Ж, Н, К,
    крыльцо, площадка); assumed - по площади основания или сооружение без подписей.
    """

    footprint: Polygon
    height_m: float
    floors: int | None
    floors_source: str
    kind: str  # building | porch | container | structure
    wall: str | None = None  # brick | metal | mixed
    use: str | None = None  # residential | non_residential
    labels: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Volumes:
    """Объёмы зданий вместе с балансом граней.

    Два равенства, по которым видна потеря: faces = len(buildings) + voids + slivers - каждая
    замкнутая грань стала объёмом, двором или отброшена как обломок; len(buildings) =
    from_labels + from_neighbors + from_letters + assumed - у каждой высоты одно основание.
    open_lines - линии слоёв зданий, не замкнувшие ни одной грани: контур, оборванный краем
    планшета, пунктир частей здания и навесов. В объёмы они не попали, но посчитаны.
    Точки на слоях зданий контуром не считаются и в балансе не участвуют.
    """

    buildings: tuple[BuildingVolume, ...] = ()
    faces: int = 0
    from_labels: int = 0
    from_neighbors: int = 0
    from_letters: int = 0
    assumed: int = 0
    voids: int = 0
    slivers: int = 0
    open_lines: int = 0
    # Сколько оборванных контуров замкнуто рамкой планшета или хордой (SHEET_M, CHORD_M):
    # основание такого дома достроено до края съёмки, и это видно в scene.json.
    closed_cuts: int = 0

    @property
    def bbox(self) -> tuple[float, float, float, float] | None:
        if not self.buildings:
            return None
        footprints = np.array([b.footprint for b in self.buildings], dtype=object)
        left, bottom, right, top = shapely.total_bounds(footprints)
        return (float(left), float(bottom), float(right), float(top))


@dataclass(frozen=True, slots=True)
class _Sign:
    """Что сказали подписи внутри грани."""

    floors: int | None = None
    wall: str | None = None
    use: str | None = None
    porch: bool = False
    container: bool = False
    ground: bool = False

    @property
    def said(self) -> bool:
        """Есть ли внутри хоть одна подпись здания: такую грань двором не признаём."""
        return bool(
            self.floors or self.wall or self.use or self.porch or self.container or self.ground
        )

    @property
    def kind(self) -> str | None:
        """Низкий объём по букве, если число этажей не подписано."""
        if self.floors:
            return None
        if self.container:
            return CONTAINER
        if self.ground:
            return STRUCTURE
        if self.porch and not (self.wall or self.use):
            return PORCH
        return None


@dataclass(frozen=True, slots=True)
class _Linework:
    """Грани, собранные из линий одного набора слоёв, и то, что гранями не стало."""

    faces: NDArray[np.object_]
    holes: NDArray[np.object_]
    slivers: int = 0
    open_lines: int = 0
    closed_cuts: int = 0

    @property
    def total(self) -> int:
        return len(self.faces) + self.slivers


def normalize_label(text: str) -> str:
    """Подпись для сравнения: без пробелов, тире - дефис, латиница - кириллица, верхний регистр."""
    return "".join(text.upper().translate(_NORMALIZE).split())


def storey_height(floors: int) -> float:
    """Высота объёма по этажности: типовой этаж плюс цоколь с парапетом (см. константы)."""
    if floors == 1:
        return ONE_STOREY_M
    return round(STOREY_M * floors + PLINTH_AND_PARAPET_M, 2)


def build_volumes(features: Sequence[Feature], labels: Sequence[TextLabel]) -> Volumes:
    """Объёмы зданий и сооружений по классифицированным объектам и подписям чертежа.

    Подписи берутся только со слоёв, на которых лежат здания: номер дома («32А», «36 СТР.9»)
    Мосгеотрест пишет на отдельном слое, и за этажность он не сойдёт. Сооружения (парапеты,
    мосты, вентиляционные киоски) собираются отдельно и получают метр высоты без подписей.
    """
    houses = [f for f in features if f.object_class is ObjectClass.BUILDING]
    layers = frozenset(f.layer for f in houses)
    own = [label for label in labels if label.layer in layers]
    ground = _ground_points(features, labels, layers)
    house_lines = _linework(houses)
    works = _linework([f for f in features if f.object_class is ObjectClass.STRUCTURE])
    homes, home_voids = _houses(house_lines, own, ground)
    structures, yards = _structures(works)
    volumes = (*homes, *structures)
    sources = Counter(v.floors_source for v in volumes)
    return Volumes(
        buildings=volumes,
        faces=house_lines.total + works.total,
        from_labels=sources[SOURCE_LABEL],
        from_neighbors=sources[SOURCE_NEIGHBOR],
        from_letters=sources[SOURCE_LETTER],
        assumed=sources[SOURCE_ASSUMED],
        voids=home_voids + yards,
        slivers=house_lines.slivers + works.slivers,
        open_lines=house_lines.open_lines + works.open_lines,
        closed_cuts=house_lines.closed_cuts + works.closed_cuts,
    )


def _houses(
    work: _Linework, labels: Sequence[TextLabel], ground: NDArray[np.object_]
) -> tuple[list[BuildingVolume], int]:
    """Здания по граням: двор отсеять, остальным дать высоту по подписи, соседу или площади."""
    faces = work.faces
    if not len(faces):
        return [], 0
    texts = _texts_by_face(faces, labels)
    signs = [_merge(_read(text) for text in own) for own in texts]
    said = np.array([sign.said for sign in signs], dtype=bool)
    open_ground = _holds(faces, ground) | _courtyards(faces, work.holes)
    void = ~said & (open_ground | (shapely.area(faces) > MAX_UNPROVEN_M2))
    floors = np.array([sign.floors or 0 for sign in signs], dtype=np.int64)
    low = np.array([sign.kind is not None for sign in signs], dtype=bool)
    inherited = _inherit(faces, floors, eligible=~void & (floors == 0) & ~low)
    volumes = [
        _volume(faces[i], signs[i], texts[i], int(inherited[i])) for i in np.flatnonzero(~void)
    ]
    return volumes, int(void.sum())


def _structures(work: _Linework) -> tuple[list[BuildingVolume], int]:
    """Сооружения: подписей у них нет, двором считается только дыра исходного полигона."""
    if not len(work.faces):
        return [], 0
    yard = _courtyards(work.faces, work.holes)
    volumes = [
        BuildingVolume(
            footprint=face,
            height_m=STRUCTURE_M,
            floors=None,
            floors_source=SOURCE_ASSUMED,
            kind=STRUCTURE,
        )
        for face in work.faces[~yard]
    ]
    return volumes, int(yard.sum())


def _volume(face: Polygon, sign: _Sign, texts: tuple[str, ...], inherited: int) -> BuildingVolume:
    """Высота грани по старшинству оснований: подпись, крыльцо и площадка, сосед, буква, площадь."""

    def made(floors: int | None, source: str, kind: str = BUILDING) -> BuildingVolume:
        heights = {PORCH: PORCH_M, CONTAINER: CONTAINER_M, STRUCTURE: STRUCTURE_M}
        height = storey_height(floors) if floors else heights[kind]
        return BuildingVolume(face, height, floors, source, kind, sign.wall, sign.use, texts)

    if sign.floors:
        return made(sign.floors, SOURCE_LABEL)
    if sign.kind is not None:
        return made(None, SOURCE_LETTER, sign.kind)
    if inherited:
        return made(inherited, SOURCE_NEIGHBOR)
    if sign.wall or sign.use:
        return made(RESIDENTIAL_FLOORS if sign.use == RESIDENTIAL else LETTER_FLOORS, SOURCE_LETTER)
    return made(_floors_by_area(face.area), SOURCE_ASSUMED)


def _floors_by_area(area: float) -> int:
    for limit, floors in AREA_FLOORS:
        if area < limit:
            return floors
    return LARGE_FLOORS


def _read(text: str) -> _Sign:
    """Одна подпись: этажность, материал стен, назначение, крыльцо, площадка или фундамент.

    Буквы и число обычно стоят отдельными текстами, но «К-5» и «КЖ9» одним текстом тоже
    читаются. Незнакомый текст (например «СТР») ничего не говорит и остаётся только в списке.
    """
    bare = text.rstrip(".")
    if text in PORCH_TEXTS:
        return _Sign(porch=True)
    if bare in CONTAINER_TEXTS:
        return _Sign(container=True)
    if bare in GROUND_TEXTS:
        return _Sign(ground=True)
    match = _SIGN.fullmatch(text)
    if match is None:
        return _Sign()
    floors = int(match["floors"]) if match["floors"] else None
    if floors is not None and not 1 <= floors <= MAX_FLOORS:
        floors = None
    return _Sign(
        floors=floors, wall=WALLS.get(match["wall"] or ""), use=USES.get(match["use"] or "")
    )


def _merge(signs: Iterable[_Sign]) -> _Sign:
    """Подписи грани вместе: наибольшая этажность, первый материал, «жилое» старше «нежилого»."""
    items = list(signs)
    uses = {s.use for s in items if s.use}
    return _Sign(
        floors=max((s.floors for s in items if s.floors), default=None),
        wall=next((s.wall for s in items if s.wall), None),
        use=RESIDENTIAL if RESIDENTIAL in uses else next(iter(uses), None),
        porch=any(s.porch for s in items),
        container=any(s.container for s in items),
        ground=any(s.ground for s in items),
    )


def _texts_by_face(
    faces: NDArray[np.object_], labels: Sequence[TextLabel]
) -> list[tuple[str, ...]]:
    """Подписи слоёв зданий по граням, в порядке чертежа."""
    texts: list[list[str]] = [[] for _ in range(len(faces))]
    kept = [(label, normalize_label(label.text)) for label in labels]
    kept = [(label, text) for label, text in kept if text]
    if kept:
        points = shapely.points([(label.x, label.y) for label, _ in kept])
        for (_, text), face in zip(kept, _owners(faces, points), strict=True):
            if face >= 0:
                texts[face].append(text)
    return [tuple(own) for own in texts]


def _owners(faces: NDArray[np.object_], points: NDArray[np.object_]) -> NDArray[np.intp]:
    """Грань каждой подписи: та, что её содержит, иначе ближайшая в пределах LABEL_REACH_M."""
    tree = STRtree(faces)
    owner = np.full(len(points), -1, dtype=np.intp)
    inside, face = tree.query(points, predicate="within")
    owner[inside] = face
    loose = np.flatnonzero(owner < 0)
    if len(loose):
        near, face = tree.query_nearest(
            points[loose], max_distance=LABEL_REACH_M, all_matches=False
        )
        owner[loose[near]] = face
    return owner


def _holds(faces: NDArray[np.object_], points: NDArray[np.object_]) -> NDArray[np.bool_]:
    """Грани, внутри которых есть признак открытой земли, а не только на их границе.

    Линия газона вдоль стены дома лежит на границе грани: её точка не должна превратить
    дом во двор, поэтому точка обязана отстоять от границы дальше допуска сшивки.
    """
    found = np.zeros(len(faces), dtype=bool)
    if not len(points):
        return found
    face, point = STRtree(points).query(faces, predicate="contains")
    inner = shapely.distance(points[point], shapely.boundary(faces[face])) > GAP_M
    found[face[inner]] = True
    return found


def _courtyards(faces: NDArray[np.object_], holes: NDArray[np.object_]) -> NDArray[np.bool_]:
    """Грани в дыре исходного полигона, прилегающие к её краю: двор, а не киоск во дворе."""
    found = np.zeros(len(faces), dtype=bool)
    if not len(holes) or not len(faces):
        return found
    face, hole = STRtree(holes).query(shapely.point_on_surface(faces), predicate="within")
    shared = shapely.length(
        shapely.intersection(
            shapely.boundary(faces[face]), shapely.boundary(holes[hole]), grid_size=GAP_M
        )
    )
    found[face[shared >= SHARED_EDGE_M]] = True
    return found


def _inherit(
    faces: NDArray[np.object_], floors: NDArray[np.int64], *, eligible: NDArray[np.bool_]
) -> NDArray[np.int64]:
    """Этажность подписанного соседа с самой длинной общей стеной, если она от SHARED_EDGE_M.

    Корпус из частей подписан обычно в одной части; остальные, прилегающие к ней, получают
    её этажность. Проход один: цепочку по соседям без подписей не тянем, чтобы этажность
    башни не расползлась по всему кварталу.
    """
    result = np.zeros(len(faces), dtype=np.int64)
    donors, takers = np.flatnonzero(floors > 0), np.flatnonzero(eligible)
    if not len(donors) or not len(takers):
        return result
    edges = shapely.boundary(faces)
    taker, donor = STRtree(edges[donors]).query(edges[takers], predicate="intersects")
    taker, donor = takers[taker], donors[donor]
    shared = shapely.length(shapely.intersection(edges[taker], edges[donor], grid_size=GAP_M))
    best: dict[int, float] = {}
    for face, other, length in zip(taker, donor, shared, strict=True):
        if length >= SHARED_EDGE_M and length > best.get(int(face), 0.0):
            best[int(face)] = float(length)
            result[face] = floors[other]
    return result


def _ground_points(
    features: Sequence[Feature], labels: Sequence[TextLabel], layers: frozenset[str]
) -> NDArray[np.object_]:
    """Точки открытой земли: объекты газона, покрытий и растительности, подписи грунта."""
    geometries = _geometries(f for f in features if f.object_class in GROUND_CLASSES)
    geometries = geometries[~shapely.is_empty(geometries)]
    soil = [
        (label.x, label.y)
        for label in labels
        if label.layer not in layers and label_material(label.text) is Material.SOIL
    ]
    spots = shapely.points(soil) if soil else _NO_GEOMETRY
    return np.concatenate([shapely.point_on_surface(geometries), spots])


def _geometries(features: Iterable[Feature]) -> NDArray[np.object_]:
    """Геометрия объектов одним массивом: shapely считает массив целиком, без цикла Python."""
    items = [f.geometry for f in features if f.geometry is not None]
    geometries = np.empty(len(items), dtype=object)
    geometries[:] = items
    return geometries


def _linework(features: Sequence[Feature]) -> _Linework:
    """Грани из линий и контуров полигонов набора: сшивка концов, разбиение, polygonize."""
    lines, holes, loose = _lines(features)
    if not len(lines):
        return _Linework(_NO_GEOMETRY, holes)
    # Сетка 2 см после сшивки: сведённые концы совпадают точно, а короткие координаты не
    # дают разбиению споткнуться о почти параллельные отрезки.
    stitched = shapely.set_precision(_stitch(lines), GAP_M)
    alive = shapely.length(stitched) > 0
    stitched, loose = stitched[alive], loose[alive]
    closers = _closers(stitched[shapely.length(stitched) >= MIN_STROKE_M])
    edges = np.concatenate([stitched, closers]) if len(closers) else stitched
    # Разбиение, а не объединение: node в разы быстрее union_all на улице из нескольких
    # планшетов и так же сводит в одно ребро стену, нарисованную на обоих планшетах.
    noded = (
        shapely.get_parts(shapely.node(shapely.multilinestrings(edges)))
        if len(edges)
        else _NO_GEOMETRY
    )
    faces = shapely.get_parts(shapely.polygonize(noded)) if len(noded) else _NO_GEOMETRY
    big = shapely.area(faces) >= MIN_FACE_M2
    return _Linework(
        faces=faces[big],
        holes=holes,
        slivers=int((~big).sum()),
        open_lines=_open_lines(stitched[loose], faces),
        closed_cuts=_used(closers, faces[big]),
    )


def _closers(strokes: NDArray[np.object_]) -> NDArray[np.object_]:
    """Куски, замыкающие оборванные контуры: рамка планшета у концов на ней и хорды цепочек."""
    if not len(strokes):
        return _NO_GEOMETRY
    chains = shapely.get_parts(shapely.line_merge(shapely.multilinestrings(strokes)))
    chords = [chord for chain in chains if (chord := _chord(chain)) is not None]
    found = [*_frame_pieces(strokes), *chords]
    return np.array(found, dtype=object) if found else _NO_GEOMETRY


def _on_frame(value: float) -> bool:
    return abs(value - round(value / SHEET_M) * SHEET_M) < FRAME_TOL_M


def _frame_pieces(strokes: NDArray[np.object_]) -> list[LineString]:
    """Кусок рамки планшета у каждого конца линии, лежащего на ней.

    Берутся концы всех линий, а не только свободные концы цепочек: дом, перешедший с листа
    на лист, в точке перехода делится рамкой на две грани, и половина, целиком лежащая на
    листе, замыкается, даже если другая половина оборвана следующей рамкой. Две грани одного
    дома получают одну этажность - по подписи или от соседа с общей стеной.
    """
    tips = shapely.get_coordinates(
        np.concatenate([shapely.get_point(strokes, 0), shapely.get_point(strokes, -1)])
    )
    pieces: list[LineString] = []
    for x, y in np.unique(tips, axis=0):
        if _on_frame(x):
            edge = round(x / SHEET_M) * SHEET_M
            pieces.append(LineString([(edge, y - FRAME_REACH_M), (edge, y + FRAME_REACH_M)]))
        if _on_frame(y):
            edge = round(y / SHEET_M) * SHEET_M
            pieces.append(LineString([(x - FRAME_REACH_M, edge), (x + FRAME_REACH_M, edge)]))
    return pieces


def _chord(chain: LineString) -> LineString | None:
    """Хорда открытой цепочки, обошедшей контур: только если вместе они дают простой полигон."""
    if chain.is_closed:
        return None
    coords = shapely.get_coordinates(chain)
    gap = float(np.hypot(*(coords[0] - coords[-1])))
    # Отрезок из двух точек отсеивает само отношение длин: у него длина равна хорде.
    if not GAP_M < gap <= CHORD_M or chain.length < CHORD_RATIO * gap:
        return None
    if not shapely.is_valid(shapely.polygons(np.vstack([coords, coords[:1]]))):
        return None
    return LineString([coords[-1], coords[0]])


def _used(closers: NDArray[np.object_], faces: NDArray[np.object_]) -> int:
    """Сколько граней замкнуто хотя бы одним замыкающим куском: столько домов достроено."""
    if not len(closers) or not len(faces):
        return 0
    edges = shapely.boundary(faces)
    piece, face = STRtree(edges).query(closers, predicate="intersects")
    shared = shapely.length(shapely.intersection(closers[piece], edges[face], grid_size=GAP_M))
    return len(np.unique(face[shared > GAP_M]))


def _lines(
    features: Sequence[Feature],
) -> tuple[NDArray[np.object_], NDArray[np.object_], NDArray[np.bool_]]:
    """Линии набора, дыры исходных полигонов и отметка, какие линии пришли не из полигона.

    Кольца полигона идут в линии наравне с полилиниями: здание из двух частей, одна из
    которых замкнута, а другая нарисована кусками, собирается в грани только вместе.
    """
    parts = shapely.get_parts(_geometries(features))
    # Пустая линия без координат сбила бы нумерацию концов при сшивке.
    parts = parts[~shapely.is_empty(parts)]
    kinds = shapely.get_type_id(parts)
    rings, owner = shapely.get_rings(parts[kinds == _POLYGON_TYPE_ID], return_index=True)
    # get_rings отдаёт наружное кольцо первым, за ним дыры того же полигона.
    exterior = np.r_[True, owner[1:] != owner[:-1]] if len(owner) else np.empty(0, dtype=bool)
    strokes = parts[np.isin(kinds, _LINE_TYPE_IDS)]
    lines = np.concatenate([rings, strokes])
    loose = np.r_[np.zeros(len(rings), dtype=bool), np.ones(len(strokes), dtype=bool)]
    return lines, shapely.polygons(rings[~exterior]), loose


def _stitch(lines: NDArray[np.object_]) -> NDArray[np.object_]:
    """Свести близкие концы в одну точку и довести конец до чужой линии рядом (Т-стык)."""
    return _snap_to_ends(_join_ends(lines))


def _join_ends(lines: NDArray[np.object_]) -> NDArray[np.object_]:
    """Концы ближе GAP_M друг к другу переносятся в одну точку - первый конец группы.

    Переносить каждый конец к ближайшему чужому нельзя: два конца поменялись бы местами, и
    разрыв остался бы. Группа (связная компонента близости) получает общего представителя.
    """
    counts = shapely.get_num_coordinates(lines)
    coords = shapely.get_coordinates(lines)
    stop = np.cumsum(counts) - 1
    ends = np.concatenate([stop - counts + 1, stop])
    pairs = KDTree(coords[ends]).query_pairs(GAP_M, output_type="ndarray")
    if not len(pairs):
        return lines
    size = len(ends)
    graph = coo_matrix(
        (np.ones(len(pairs), dtype=np.int8), (pairs[:, 0], pairs[:, 1])), shape=(size, size)
    )
    _, group = connected_components(graph, directed=False)
    leader = np.full(group.max() + 1, size, dtype=np.intp)
    np.minimum.at(leader, group, np.arange(size))
    moved = coords.copy()
    moved[ends] = coords[ends[leader[group]]]
    return shapely.set_coordinates(lines.copy(), moved)


def _snap_to_ends(lines: NDArray[np.object_]) -> NDArray[np.object_]:
    """Линия, мимо которой в пределах GAP_M проходит чужой конец, получает вершину в нём."""
    tips = np.concatenate([shapely.get_point(lines, 0), shapely.get_point(lines, -1)])
    ends = shapely.points(np.unique(shapely.get_coordinates(tips), axis=0))
    line, end = STRtree(ends).query(lines, predicate="dwithin", distance=GAP_M)
    near = shapely.distance(lines[line], ends[end]) > 0
    line, end = line[near], end[near]
    if not len(line):
        return lines
    order = np.argsort(line, kind="stable")
    line, end = line[order], end[order]
    targets, slot = np.unique(line, return_inverse=True)
    anchors = shapely.multipoints(ends[end], indices=slot)
    snapped = lines.copy()
    snapped[targets] = shapely.snap(lines[targets], anchors, GAP_M)
    return snapped


def _open_lines(lines: NDArray[np.object_], faces: NDArray[np.object_]) -> int:
    """Сколько линий (не контуров полигонов) не легли на границу ни одной грани."""
    if not len(lines) or not len(faces):
        return len(lines)
    edges = shapely.boundary(faces)
    line, face = STRtree(edges).query(lines, predicate="intersects")
    shared = shapely.length(shapely.intersection(lines[line], edges[face], grid_size=GAP_M))
    return len(lines) - len(np.unique(line[shared > GAP_M]))
