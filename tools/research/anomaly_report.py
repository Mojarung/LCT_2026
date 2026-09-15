"""6 контрольных участков нарушений отступов: PNG, xlsx со всеми нарушениями, DXF-оверлей с маркерами."""
import sys, pickle
from pathlib import Path
import numpy as np
import pandas as pd
import ezdxf
import matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt
from shapely import from_wkb
from shapely.geometry import Point, box

prov = pickle.load(open(sys.argv[1], 'rb')); df = pd.read_pickle(sys.argv[2]); out = Path(sys.argv[3]); out.mkdir(parents=True, exist_ok=True)
AXIS = ('msdElementTypeMultiLine', 'msdElementTypeLineString', 'msdElementTypeComplexString')
ORDER = ['Кабель электрический', 'Водопровод', 'Теплосеть', 'Кабель связи', 'Кабель электрический', 'Канализация самотёчная', 'Газопровод']
sites = []
for cls in ORDER:
    if len(sites) == 6: break
    cand = df[(df['сеть'] == cls) & df['тип_элемента'].str.startswith(AXIS) & (df['длина_элемента_м'] >= 1.0)]
    for _, r in cand.iterrows():
        if all(np.hypot(r.X - s.X, r.Y - s.Y) > 60 for s in sites):
            sites.append(r); break
COL = {'Кабель электрический': '#d62728', 'Водопровод': '#1f77b4', 'Канализация самотёчная': '#8c564b', 'Газопровод': '#d4a000',
       'Теплосеть': '#ff7f0e', 'Кабель связи': '#9467bd', 'Водосток': '#17becf', 'Кабели': '#e377c2', 'Бортовой камень': '#444444',
       'Здания': '#000000', 'Колодцы': '#7f7f7f', 'Фонари': '#9a9a00'}
H = 12
recs = prov['recs']
geoms = [(r, from_wkb(r['wkb'])) for r in recs if r['cls'] in COL]
summary = []
for n, s in enumerate(sites, 1):
    win = box(s.X - H, s.Y - H, s.X + H, s.Y + H)
    fig, ax = plt.subplots(figsize=(11, 11))
    for r, g in geoms:
        if not g.intersects(win): continue
        x, y = g.xy
        ax.plot(x, y, color=COL[r['cls']], lw=1.3, ls='-' if '-24_' in r['xref'] else '--', alpha=.9)
    for k, c in COL.items(): ax.plot([], [], color=c, label=k)
    ax.plot([], [], color='k', ls='-', label='сплошная — подоснова ДЖКХ-24_03233'); ax.plot([], [], color='k', ls='--', label='пунктир — подоснова ДЖКХ-25_01840')
    for t in prov['trees']:
        if win.contains(Point(t['x'], t['y'])):
            ax.add_patch(plt.Circle((t['x'], t['y']), t['r'], fill=False, color='#2ca02c', lw=1.2)); ax.plot(t['x'], t['y'], '+', color='#2ca02c')
    g = from_wkb(s.wkb); x, y = g.xy; ax.plot(x, y, color=COL[s['сеть']], lw=5, alpha=.35)
    ax.add_patch(plt.Circle((s.X, s.Y), s['радиус_кроны'], fill=False, color='magenta', lw=3))
    ax.plot([s.X, s['точка_сети_X']], [s.Y, s['точка_сети_Y']], color='magenta', lw=2)
    ax.annotate(f"{s['порода']}  {s['расстояние_м']:.2f} м до «{s['сеть']}» (норма {s['норма_м']} м)", (s.X, s.Y), xytext=(10, 25),
                textcoords='offset points', fontsize=11, color='magenta', weight='bold', bbox=dict(fc='white', ec='magenta', alpha=.9))
    others = df[(abs(df.X - s.X) < H) & (abs(df.Y - s.Y) < H)]
    ax.set_xlim(s.X - H, s.X + H); ax.set_ylim(s.Y - H, s.Y + H); ax.set_aspect('equal'); ax.grid(alpha=.3)
    ax.legend(fontsize=8, loc='lower left', framealpha=.9)
    ax.set_title(f"Участок {n}. X={s.X:.2f}  Y={s.Y:.2f}   AutoCAD: _ZOOM _C {s.X:.2f},{s.Y:.2f} 25\n"
                 f"Слой дерева: {s['дерево_слой']} (handle {s['дерево_handle']}).  Сеть: {s['слой_сети'].split('$0$')[-1]}, "
                 f"xref {s['xref']}, элемент {s['тип_элемента']} {s['длина_элемента_м']} м.  Нарушений в окне: {len(others)}", fontsize=9)
    f = out / f"участок_{n}_{s['сеть'].replace(' ', '_')}.png"; fig.savefig(f, dpi=105, bbox_inches='tight'); plt.close(fig)
    summary.append(dict(участок=n, сеть=s['сеть'], порода=s['порода'], X=s.X, Y=s.Y, расстояние_м=s['расстояние_м'], норма_м=s['норма_м'],
                        xref=s['xref'], дерево_handle=s['дерево_handle'], команда=f"_ZOOM _C {s.X:.2f},{s.Y:.2f} 25", нарушений_в_окне=len(others), png=f.name))

df2 = df.drop(columns=['wkb']).copy()
df2['команда_AutoCAD'] = [f"_ZOOM _C {x:.2f},{y:.2f} 25" for x, y in zip(df2.X, df2.Y)]
with pd.ExcelWriter(out / 'нарушения_отступов_Берзарина.xlsx') as w:
    pd.DataFrame(summary).to_excel(w, sheet_name='6 участков', index=False)
    df2.to_excel(w, sheet_name='все нарушения', index=False)

doc = ezdxf.new('R2013'); msp = doc.modelspace()
for name, color in (('!АНОМАЛИЯ_дерево', 6), ('!АНОМАЛИЯ_до_сети', 6), ('!АНОМАЛИЯ_подпись', 2), ('!АНОМАЛИЯ_участок', 3)):
    doc.layers.add(name, color=color)
for _, r in df.iterrows():
    msp.add_circle((r.X, r.Y), r['радиус_кроны'] + 0.3, dxfattribs={'layer': '!АНОМАЛИЯ_дерево'})
    msp.add_line((r.X, r.Y), (r['точка_сети_X'], r['точка_сети_Y']), dxfattribs={'layer': '!АНОМАЛИЯ_до_сети'})
    msp.add_text(f"{r['расстояние_м']:.2f}м {r['сеть']}", height=0.3, dxfattribs={'layer': '!АНОМАЛИЯ_подпись'}).set_placement((r.X + 0.4, r.Y + 0.4))
for srow in summary:
    msp.add_lwpolyline([(srow['X'] - H, srow['Y'] - H), (srow['X'] + H, srow['Y'] - H), (srow['X'] + H, srow['Y'] + H), (srow['X'] - H, srow['Y'] + H)],
                       close=True, dxfattribs={'layer': '!АНОМАЛИЯ_участок', 'const_width': 0.15})
    msp.add_text(f"УЧАСТОК {srow['участок']}", height=1.5, dxfattribs={'layer': '!АНОМАЛИЯ_участок'}).set_placement((srow['X'] - H, srow['Y'] + H + 0.5))
doc.saveas(out / 'нарушения_маркеры_Берзарина.dxf')
print(pd.DataFrame(summary)[['участок', 'сеть', 'порода', 'X', 'Y', 'расстояние_м', 'xref', 'дерево_handle', 'нарушений_в_окне']].to_string(index=False))
