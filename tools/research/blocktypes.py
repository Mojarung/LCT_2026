import sys, collections, re, numpy as np
from ezdxf import recover
doc, aud = recover.readfile(sys.argv[1]); msp = doc.modelspace()
def short(s): return s.split('$0$')[-1]
UTIL = {'Водопровод','Газопровод','Теплосеть','Кабель электрический','Канализация самотёчная','Кабель связи','Водосток','Кабели','Бортовой камень','Отдельно стоящее дерево'}
stat = collections.defaultdict(lambda: collections.defaultdict(list))
def length(ents):
    L=0; nv=0; types=collections.Counter()
    for v in ents:
        t=v.dxftype(); types[t]+=1
        if t=='LINE': L+=v.dxf.start.distance(v.dxf.end); nv+=2
        elif t=='LWPOLYLINE':
            p=np.array([q[:2] for q in v.get_points('xy')]); nv+=len(p)
            if len(p)>1: L+=np.linalg.norm(np.diff(p,axis=0),axis=1).sum()
    return L,nv,types
def walk(e, depth):
    if e.dxftype()!='INSERT' or depth>4: return
    for v in e.virtual_entities():
        if v.dxftype()=='INSERT':
            lay = short(v.dxf.layer); bn = short(v.dxf.name)
            if lay in UTIL and not bn.startswith('output'):
                base = re.sub(r'_\d+$','',bn)
                L,nv,types = length(v.virtual_entities())
                s = stat[(lay,base)]; s['L'].append(L); s['nv'].append(nv); s['t'].append('+'.join(sorted(types)))
            else: walk(v, depth+1)
for e in msp: walk(e,0)
for (lay,base),s in sorted(stat.items(), key=lambda x:(x[0][0],-len(x[1]['L']))):
    L=np.array(s['L']); print(f"{lay:24s} {base:34s} n={len(L):5d} lenP50={np.median(L):7.2f} lenP90={np.percentile(L,90):7.2f} nvP50={int(np.median(s['nv']))} types={collections.Counter(s['t']).most_common(2)}")
