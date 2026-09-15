import pickle, sys, numpy as np
import matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt
from shapely import from_wkb
from shapely.geometry import Point, box
from shapely.strtree import STRtree
d = pickle.load(open(sys.argv[1],'rb'))
lines = {k:[from_wkb(g) for g in v] for k,v in d['lines'].items()}
el = lines['Кабель электрический']; tr = STRtree(el)
pts = [(sp,p,r) for sp in d['trees'] for p,r in zip(d['trees'][sp], d['radii'][sp]) if r>=1.5]
# find the densest window of violations
viol = [p for sp,p,r in pts if min(el[i].distance(Point(p)) for i in np.atleast_1d(tr.query_nearest(Point(p)))) < 1.0]
cx, cy = np.median(np.array(viol), axis=0) if viol else (0,0)
if len(sys.argv)>3: cx, cy = float(sys.argv[3]), float(sys.argv[4])
W = float(sys.argv[5]) if len(sys.argv)>5 else 40
win = box(cx-W, cy-W, cx+W, cy+W)
col = {'Кабель электрический':'#d62728','Водопровод':'#1f77b4','Канализация самотёчная':'#8c564b','Газопровод':'#e6b800','Теплосеть':'#ff7f0e','Кабель связи':'#9467bd','Водосток':'#17becf','Кабели':'#e377c2','Бортовой камень':'#555555','Здания':'#000000','Колодцы':'#7f7f7f','Отдельно стоящее дерево':'#2ca02c','Ограды':'#aaaaaa','Фонари':'#bcbd22'}
fig, ax = plt.subplots(figsize=(13,13))
for k,c in col.items():
    for g in lines.get(k,[]):
        if g.intersects(win):
            x,y = g.xy if g.geom_type!='Point' else ([g.x],[g.y]); ax.plot(x,y,color=c,lw=1.2 if k not in('Здания','Бортовой камень') else 0.8, marker='.' if g.geom_type=='Point' else None, ms=3)
    ax.plot([],[],color=c,label=k)
for k,v in d['design'].items():
    c = '#00aa00' if k.startswith(('06','6_')) else ('#ff00ff' if 'Отступ' in k else ('#006600' if k.startswith(('05','5_')) else '#444'))
    for w in v:
        g = from_wkb(w)
        if g.intersects(win): x,y = g.xy; ax.plot(x,y,color=c,lw=1.8 if 'Отступ' in k else 1.0, ls='--' if 'Отступ' in k else '-')
for sp,p,r in pts:
    if win.contains(Point(p)): ax.plot(*p,'g+',ms=8); ax.text(p[0],p[1],sp[:8],fontsize=6)
ax.plot([],[],color='#00aa00',label='проектные посадки 06_'); ax.plot([],[],color='#ff00ff',ls='--',label='01_План_Отступы'); ax.plot([],[],color='#006600',label='сущ. 05_')
ax.set_xlim(cx-W,cx+W); ax.set_ylim(cy-W,cy+W); ax.set_aspect('equal'); ax.legend(fontsize=8, loc='upper right'); ax.grid(alpha=.3)
ax.set_title(f'Берзарина, окно {2*W:.0f}x{2*W:.0f} м вокруг ({cx:.0f},{cy:.0f}); деревьев с кабелем <1м: {len(viol)}')
fig.savefig(sys.argv[2], dpi=110, bbox_inches='tight'); print(cx, cy, len(viol))
