"""Разбор DXF с происхождением каждой геометрии: слой, xref, вложенный блок, видимость, XCLIP."""
import sys, re, pickle, time, collections
from ezdxf import recover, path as ezpath
from shapely.geometry import LineString, Point
from shapely import to_wkb

t0 = time.time()
doc, aud = recover.readfile(sys.argv[1])
msp = doc.modelspace()
print("load", round(time.time() - t0), "s")

def short(s): return s.split('$0$')[-1]
NET = {'Водопровод','Водосток','Канализация самотёчная','Канализация напорная','Газопровод','Теплосеть',
       'Кабель электрический','Кабель связи','Кабели','Кабель защиты','Общий коллектор','Дренаж','Подземные коммуникации',
       'Кабель электрический проектный','Водопровод проектный','Кабель связи проектный','Теплосеть проектная',
       'Газопровод проектный','Водосток проектный','Канализация самотёчная проектная','Кабели проектные','Трубопроводы проектные'}
CTX = {'Бортовой камень','Здания','Колодцы','Фонари','Отдельно стоящее дерево','Граница улицы','Ограды'}
SKIP_BLOCK = re.compile(r'^(DIMTXT|msdElementTypeTextNode)(_\d+)?$')

_ls = {}
def layer_flags(name):
    if name not in _ls:
        if doc.layers.has_entry(name):
            l = doc.layers.get(name); _ls[name] = (l.is_off(), l.is_frozen())
        else:
            _ls[name] = (False, False)
    return _ls[name]

clip_count = collections.Counter()
def has_clip(ins):
    try:
        if ins.has_extension_dict:
            xd = ins.get_extension_dict()
            if 'ACAD_FILTER' in xd: return True
    except Exception:
        pass
    return False

def to_geom(v):
    try:
        p = ezpath.make_path(v)
        pts = [(q.x, q.y) for q in p.flattening(0.05)]
    except Exception:
        return None
    if len(pts) < 2: return None
    return LineString(pts)

recs = []
def walk(e, chain, top):
    for v in e.virtual_entities():
        full = v.dxf.layer
        eff = chain[-1]['layer'] if full == '0' and chain else full
        if v.dxftype() == 'INSERT':
            bn = short(v.dxf.name)
            if SKIP_BLOCK.match(bn): continue
            node = {'layer': eff, 'block': bn, 'clip': has_clip(v)}
            if node['clip']: clip_count[bn] += 1
            walk(v, chain + [node], top)
            continue
        s = short(eff)
        if s not in NET and s not in CTX: continue
        g = to_geom(v)
        if g is None: continue
        off, frz = layer_flags(eff)
        chain_frozen = any(layer_flags(n['layer'])[1] for n in chain) or layer_flags(top['layer'])[1]
        nested = next((n['block'] for n in reversed(chain) if not n['block'].startswith('output')), '')
        xref = next((n['block'] for n in chain if n['block'].startswith('output')), top['block'])
        recs.append(dict(cls=s, full_layer=eff, xref=xref, top_block=top['block'], top_handle=top['handle'],
                         nested_block=re.sub(r'_\d+$', '', nested), hidden=bool(off or frz or chain_frozen),
                         clipped_xref=any(n['clip'] for n in chain) or top['clip'], length=g.length, wkb=to_wkb(g)))

trees = []
for e in msp:
    if e.dxftype() == 'INSERT':
        top = {'block': short(e.dxf.name), 'layer': e.dxf.layer, 'handle': e.dxf.handle, 'clip': has_clip(e)}
        if top['clip']: clip_count['TOP:' + top['block']] += 1
        try: walk(e, [], top)
        except Exception as ex: print("walk err", top['block'], ex)
    elif e.dxftype() == 'CIRCLE':
        m = re.match(r'^0?6_+ДП_(.+)_план$', e.dxf.layer)
        if m:
            off, frz = layer_flags(e.dxf.layer)
            trees.append(dict(handle=e.dxf.handle, species=m.group(1), layer=e.dxf.layer, x=e.dxf.center.x, y=e.dxf.center.y,
                              r=e.dxf.radius, hidden=bool(off or frz)))
print("walk", round(time.time() - t0), "s; net/ctx recs", len(recs), "trees", len(trees))
print("xclip:", dict(clip_count))
hid = collections.Counter((r['cls'], r['hidden']) for r in recs)
print("hidden by class:", {k: v for k, v in sorted(hid.items())})
print("xref by class (Кабель электрический):", collections.Counter(r['xref'] for r in recs if r['cls'] == 'Кабель электрический').most_common(12))
pickle.dump({'recs': recs, 'trees': trees}, open(sys.argv[2], 'wb'))
