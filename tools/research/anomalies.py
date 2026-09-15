"""Нарушения отступов деревьев от сетей в эталоне, с разбивкой по источнику геометрии."""
import sys, pickle, collections
import numpy as np
import pandas as pd
from shapely import from_wkb
from shapely.geometry import Point
from shapely.ops import nearest_points
from shapely.strtree import STRtree

d = pickle.load(open(sys.argv[1], 'rb'))
SHRUB = ('Бересклет', 'Боярышник', 'Сирень', 'Скумпия', 'Чубушник', 'Лещина', 'Бузина', 'Туя')
NORM = {'Кабель электрический': 2.0, 'Водопровод': 2.0, 'Теплосеть': 2.0, 'Кабель связи': 2.0,
        'Канализация самотёчная': 1.5, 'Газопровод': 1.5}
trees = [t for t in d['trees'] if not t['species'].startswith(SHRUB) and t['r'] >= 1.0]
print("деревьев:", len(trees))
AXIS = ('msdElementTypeMultiLine', 'msdElementTypeLineString', 'msdElementTypeComplexString')

def run(filter_fn, label):
    out = {}
    for cls, nrm in NORM.items():
        rs = [r for r in d['recs'] if r['cls'] == cls and filter_fn(r)]
        if not rs: continue
        gs = [from_wkb(r['wkb']) for r in rs]; tr = STRtree(gs)
        dist = []
        for t in trees:
            p = Point(t['x'], t['y']); i = int(np.atleast_1d(tr.query_nearest(p))[0]); dist.append(gs[i].distance(p))
        out[cls] = np.mean(np.array(dist) < nrm)
    print(f"{label:42s} " + "  ".join(f"{k[:10]}={v:5.1%}" for k, v in out.items()))

run(lambda r: True, "вся геометрия")
run(lambda r: '-25_' in r['xref'], "только новая подоснова ДЖКХ-25")
run(lambda r: '-24_' in r['xref'], "только старая подоснова ДЖКХ-24")
run(lambda r: r['nested_block'].startswith(AXIS), "только оси (MultiLine/LineString)")
run(lambda r: r['nested_block'].startswith(AXIS) and '-25_' in r['xref'], "оси + ДЖКХ-25")

rows = []
for cls, nrm in NORM.items():
    rs = [r for r in d['recs'] if r['cls'] == cls]
    gs = [from_wkb(r['wkb']) for r in rs]; tr = STRtree(gs)
    for t in trees:
        p = Point(t['x'], t['y']); i = int(np.atleast_1d(tr.query_nearest(p))[0]); g = gs[i]; dist = g.distance(p)
        if dist >= nrm: continue
        r = rs[i]; q = nearest_points(p, g)[1]
        rows.append(dict(порода=t['species'], дерево_handle=t['handle'], дерево_слой=t['layer'], X=round(t['x'], 2), Y=round(t['y'], 2),
                         радиус_кроны=round(t['r'], 2), сеть=cls, норма_м=nrm, расстояние_м=round(dist, 2),
                         точка_сети_X=round(q.x, 2), точка_сети_Y=round(q.y, 2), слой_сети=r['full_layer'], xref=r['xref'],
                         версия_подосновы='ДЖКХ-25' if '-25_' in r['xref'] else ('ДЖКХ-24' if '-24_' in r['xref'] else r['xref']),
                         тип_элемента=r['nested_block'], длина_элемента_м=round(r['length'], 2), скрыт=r['hidden'],
                         вставка_handle=r['top_handle'], wkb=r['wkb']))
df = pd.DataFrame(rows).sort_values('расстояние_м')
df.to_pickle(sys.argv[2])
print("\nнарушений (дерево×сеть):", len(df), " уникальных деревьев:", df['дерево_handle'].nunique())
print(df.groupby(['сеть', 'версия_подосновы']).size().unstack(fill_value=0))
print(df.groupby('тип_элемента').size().sort_values(ascending=False).head(8))
print(df[['порода', 'X', 'Y', 'сеть', 'расстояние_м', 'версия_подосновы', 'тип_элемента', 'длина_элемента_м']].head(15).to_string())
