import sys, collections, re
from ezdxf import recover
doc, aud = recover.readfile(sys.argv[1])
msp = doc.modelspace()
cnt = collections.Counter(); kinds = collections.Counter(); blk = collections.Counter(); attrs = collections.Counter()
samples = {}
def short(l): return l.split('$0$')[-1]
def walk(e, kind, depth=0):
    t = e.dxftype()
    if t == 'INSERT':
        bn = short(e.dxf.name)
        if depth>0 and not bn.startswith(('output','link','*')):
            blk[(kind, short(e.dxf.layer), bn)] += 1
            for a in e.attribs: attrs[(bn, a.dxf.tag)] += 1
            if bn not in samples: samples[bn] = (short(e.dxf.layer), [(a.dxf.tag, a.dxf.text) for a in e.attribs][:6], tuple(round(v,2) for v in e.dxf.insert)[:2], round(e.dxf.xscale,3))
            cnt[(kind, short(e.dxf.layer), 'INSERT')] += 1
            return
        try:
            for v in e.virtual_entities(): walk(v, kind, depth+1)
        except Exception as ex: cnt[(kind,'ERR',type(ex).__name__)] += 1
    else:
        cnt[(kind, short(e.dxf.layer), t)] += 1
for e in msp:
    if e.dxftype()=='INSERT':
        m = re.search(r'01840(\w+)$|_(brd)$|^(link.*)$', short(e.dxf.name))
        kind = (m.group(1) or m.group(2) or 'link') if m else short(e.dxf.name)
    else: kind='msp'
    walk(e, kind)
by = collections.defaultdict(collections.Counter)
for (k,l,t),c in cnt.items(): by[(k,l)][t]+=c
for k in sorted({k for k,_ in by}):
    print(f"===== {k}")
    for (kk,l) in sorted([x for x in by if x[0]==k], key=lambda x:-sum(by[x].values())):
        print(f"{sum(by[(kk,l)].values()):7d}  {l}  {dict(by[(kk,l)])}")
print("===== nested blocks (kind, layer, block)")
for (k,l,b),c in blk.most_common(80): print(f"{c:6d} {k} | {l} | {b} | {samples.get(b)}")
print("===== attrib tags"); 
for (b,t),c in attrs.most_common(30): print(c,b,t)
