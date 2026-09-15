import sys, collections, ezdxf, time
t=time.time()
from ezdxf import recover
doc, aud = recover.readfile(sys.argv[1]); print("audit errors", len(aud.errors), "fixes", len(aud.fixes))
msp = doc.modelspace()
print("version", doc.dxfversion, "units", doc.header.get('$INSUNITS'), "load", round(time.time()-t,1),"s")
print("extmin", doc.header.get('$EXTMIN'), "extmax", doc.header.get('$EXTMAX'))
cnt = collections.Counter(); blk = collections.Counter()
for e in msp:
    lay = e.dxf.layer
    short = lay.split('$0$')[-1] if '$0$' in lay else lay
    cnt[(short, e.dxftype())] += 1
    if e.dxftype()=='INSERT': blk[(short, e.dxf.name.split('$0$')[-1])] += 1
print("modelspace entities", sum(cnt.values()))
bylayer = collections.defaultdict(dict)
for (l,t_),c in cnt.items(): bylayer[l][t_]=c
for l in sorted(bylayer, key=lambda l:-sum(bylayer[l].values())):
    print(f"{sum(bylayer[l].values()):7d}  {l}  {bylayer[l]}")
print("--- top INSERT blocks")
for (l,b),c in blk.most_common(60): print(f"{c:6d} {l} :: {b}")
print("blocks defined", len(doc.blocks))
