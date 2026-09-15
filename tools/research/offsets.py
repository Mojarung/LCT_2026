import sys, collections, re, time
import numpy as np
from ezdxf import recover
from shapely.geometry import LineString, Point
from shapely.strtree import STRtree
t=time.time()
doc, aud = recover.readfile(sys.argv[1]); print("load", round(time.time()-t), "s")
msp = doc.modelspace()
def short(l): return l.split('$0$')[-1]
UTIL = ['Водопровод','Водосток','Канализация самотёчная','Канализация напорная','Газопровод','Теплосеть','Кабель электрический','Кабель связи','Кабели','Кабель защиты','Общий коллектор','Дренаж','Подземные коммуникации']
OTHER = ['Бортовой камень','Здания','Фонари','Колодцы','Ограды','Отдельно стоящее дерево']
lines = collections.defaultdict(list); radii = collections.defaultdict(list); trees = collections.defaultdict(list)
texts = collections.Counter()
def geom(e, layer):
    t = e.dxftype()
    try:
        if t == 'LINE': return LineString([(e.dxf.start.x,e.dxf.start.y), (e.dxf.end.x,e.dxf.end.y)])
        if t == 'LWPOLYLINE':
            pts = [tuple(p) for p in e.get_points('xy')]
            if e.closed: pts.append(pts[0])
            return LineString(pts) if len(pts)>1 else None
        if t == 'POLYLINE':
            pts = [(v.dxf.location.x,v.dxf.location.y) for v in e.vertices]
            return LineString(pts) if len(pts)>1 else None
        if t == 'CIRCLE': return Point(e.dxf.center.x,e.dxf.center.y).buffer(max(e.dxf.radius,0.05)).exterior
        if t == 'INSERT': return Point(e.dxf.insert.x,e.dxf.insert.y)
    except Exception: return None
def walk(e, parent_layer, depth=0):
    lay = short(e.dxf.layer)
    if lay == '0' and parent_layer: lay = parent_layer
    t = e.dxftype()
    if t == 'INSERT' and re.match(r'(DIMTXT|msdElementTypeTextNode)(_[0-9]+)?$', short(e.dxf.name)): return
    if t == 'INSERT' and depth < 6:
        try:
            for v in e.virtual_entities(): walk(v, lay if lay!='0' else parent_layer, depth+1)
        except Exception: pass
        if lay in OTHER and depth>0:
            g = geom(e, lay)
            if g is not None: lines[lay].append(g)
        return
    if lay in UTIL or lay in OTHER:
        g = geom(e, lay)
        if g is not None: lines[lay].append(g)
    m = re.match(r'0?6_+ДП_(.+)_план', lay)
    if m and t == 'CIRCLE' and depth == 0:
        trees[m.group(1)].append((e.dxf.center.x,e.dxf.center.y)); radii[m.group(1)].append(e.dxf.radius)
for e in msp: walk(e, None)
print("load+walk", round(time.time()-t), "s")
print({k:len(v) for k,v in lines.items()})
print("--- planned tree circles: species n radius(p50)")
allpts = []
for sp in sorted(trees, key=lambda s:-len(trees[s])):
    r = np.array(radii[sp]); print(f"{sp:28s} n={len(r):4d} r_p50={np.median(r):.2f} r_min={r.min():.2f} r_max={r.max():.2f}")
    allpts += [(sp,p,rr) for p,rr in zip(trees[sp], radii[sp])]
big = [x for x in allpts if x[2] >= 1.0]
print("--- distance from planned CIRCLE centers (r>=1.0m, i.e. trees/big shrubs, n=%d) to nearest object" % len(big))
for lay in UTIL+OTHER:
    if not lines[lay]: continue
    tree = STRtree(lines[lay])
    d = []
    for sp,p,rr in big:
        pt = Point(p); idx = tree.query_nearest(pt)
        d.append(min(lines[lay][i].distance(pt) for i in np.atleast_1d(idx)))
    d = np.array(d)
    print(f"{lay:26s} objs={len(lines[lay]):5d}  p1={np.percentile(d,1):6.2f} p5={np.percentile(d,5):6.2f} p10={np.percentile(d,10):6.2f} p50={np.median(d):6.2f}  share<1.5m={np.mean(d<1.5):.2f} share<2m={np.mean(d<2):.2f}")
import pickle
from shapely import to_wkb
other_lay = collections.defaultdict(list)
for e in msp:
    lay = short(e.dxf.layer)
    if re.match(r'(01_План_Отступы|0?5_ДП_.+_Сущ|0?6_+ДП_.+_план|ГП_Граница проектирования|ДВ_ГП_П_Борт.*)$', lay):
        g = geom(e, lay)
        if g is not None: other_lay[lay].append(to_wkb(g))
pickle.dump({'lines':{k:[to_wkb(g) for g in v] for k,v in lines.items()}, 'trees':dict(trees), 'radii':dict(radii), 'design':dict(other_lay)}, open(sys.argv[2],'wb'))
print("cached")
