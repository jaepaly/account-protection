"""Chen 표기 EER 다이어그램 생성기 — 도형은 SVG로 직접 그리고, 배치는 ELK(layered)에 맡긴다.

표기 (강의자료 3. Data Modeling 기준)
  개체 = 사각형, 약한 개체 = 이중 사각형, 관계 = 마름모, 식별 관계 = 이중 마름모,
  속성 = 타원(키 = 밑줄, 부분키 = 점선 밑줄, 유도 = 점선 타원, 다중값 = 이중 타원),
  전체 참여 = 이중선, 특수화 = 원(d: 분리, o: 중복) + 하위 개체 선의 부분집합 기호(⊂)
"""
import json
import subprocess
from html import escape
from pathlib import Path

HERE = Path(__file__).resolve().parent
FONT = "'Malgun Gothic', sans-serif"
FS = 13


def text_w(s: str, fs: float = FS) -> float:
    w = 0.0
    for ch in s:
        if ord(ch) >= 0x2E80:
            w += fs * 1.0
        elif ch in 'iljI.,:;|!()[]\' ':
            w += fs * 0.33
        else:
            w += fs * 0.6
    return w


class Fig:
    def __init__(self, direction='RIGHT', spacing=26, layer_spacing=42):
        self.nodes, self.edges = {}, []
        self.attr_straight = True
        self.opts = {
            'elk.algorithm': 'layered', 'elk.direction': direction, 'elk.edgeRouting': 'ORTHOGONAL',
            'elk.spacing.nodeNode': str(spacing), 'elk.layered.spacing.nodeNodeBetweenLayers': str(layer_spacing),
            'elk.spacing.edgeNode': '14', 'elk.spacing.edgeEdge': '9',
            'elk.layered.spacing.edgeNodeBetweenLayers': '14',
            'elk.layered.nodePlacement.strategy': 'NETWORK_SIMPLEX',
            'elk.layered.considerModelOrder.strategy': 'NODES_AND_EDGES',
            'elk.padding': '[top=12,left=12,bottom=12,right=12]',
        }

    # ---------------------------------------------------------------- 노드
    def entity(self, nid, label, weak=False, ref=False):
        w = max(text_w(label) + (34 if weak else 26), 78)
        self.nodes[nid] = dict(kind='entity', label=label, weak=weak, ref=ref, w=w, h=40 if weak else 36)
        return nid

    def rel(self, nid, label, ident=False):
        w = text_w(label) + (64 if ident else 52)
        self.nodes[nid] = dict(kind='rel', label=label, ident=ident, w=w, h=50 if ident else 44, ports=True)
        return nid

    def spec(self, nid, kind='d'):
        self.nodes[nid] = dict(kind='spec', label=kind, w=28, h=28, ports=True)
        return nid

    def text(self, nid, label, size=12):
        self.nodes[nid] = dict(kind='text', label=label, size=size, w=text_w(label, size), h=size + 4)
        return nid

    def attr(self, nid, label, key=False, partial=False, derived=False, multi=False):
        w = text_w(label) + 30
        self.nodes[nid] = dict(kind='attr', label=label, key=key, partial=partial, derived=derived, multi=multi,
                               w=w + (6 if multi else 0), h=32 if multi else 28)
        return nid

    # ---------------------------------------------------------------- 연결
    def edge(self, a, b, total=False, card=None, card_at='b', subset=False, straight=False, label=None):
        self.edges.append(dict(a=a, b=b, total=total, card=card, card_at=card_at, subset=subset,
                               straight=straight, label=label))

    def relate(self, a, label, b, card=('1', 'N'), total=(False, False), ident=False, rid=None):
        """a —(관계)— b. card/total 은 (a 쪽, b 쪽). 카디널리티는 마름모 가까이에 쓴다."""
        rid = rid or f'r_{a}_{b}_{len(self.edges)}'
        self.rel(rid, label, ident=ident)
        self.edge(a, rid, total=total[0], card=card[0], card_at='b')
        self.edge(rid, b, total=total[1], card=card[1], card_at='a')
        return rid

    def specialize(self, sup, subs, kind='d', total=True, sid=None, on=None):
        """on = 특수화를 결정하는 속성(정의 속성) — 상위 개체→원 선 옆에 표시"""
        sid = sid or f's_{sup}'
        self.spec(sid, kind)
        self.edge(sup, sid, total=total, label=on)
        for s in subs:
            self.edge(sid, s, subset=True)
        return sid

    def has(self, owner, *attrs):
        for a in attrs:
            self.edge(owner, a, straight=True)

    # ---------------------------------------------------------------- 수동 배치 (영역별 상세도)
    def place(self, nid, cx, cy):
        self.nodes[nid]['cx'], self.nodes[nid]['cy'] = cx, cy

    def fan(self, owner, ids, a0, a1, r1, r2=None):
        """owner 중심에서 a0→a1도(0=동, 90=남) 사이에 속성을 고르게 놓는다. r2 를 주면 반지름을 번갈아 써서 겹침을 피한다."""
        import math
        o, n = self.nodes[owner], len(ids)
        for i, aid in enumerate(ids):
            a = math.radians(a0 + (a1 - a0) * (i / (n - 1) if n > 1 else 0.5))
            r = r1 if r2 is None or i % 2 == 0 else r2
            self.place(aid, o['cx'] + r * math.cos(a), o['cy'] + r * math.sin(a))

    def layout_manual(self, margin=16):
        for n in self.nodes.values():
            n['x'], n['y'] = n['cx'] - n['w'] / 2, n['cy'] - n['h'] / 2
        dx = margin - min(n['x'] for n in self.nodes.values())
        dy = margin - min(n['y'] for n in self.nodes.values())
        for n in self.nodes.values():
            n['x'] += dx; n['y'] += dy; n['cx'] += dx; n['cy'] += dy
        for e in self.edges:
            e['pts'] = straight(self.nodes[e['a']], self.nodes[e['b']])
        self.W = max(n['x'] + n['w'] for n in self.nodes.values()) + margin
        self.H = max(n['y'] + n['h'] for n in self.nodes.values()) + margin

    # ---------------------------------------------------------------- 자동 배치 (전체도)
    def layout(self):
        children = []
        for nid, n in self.nodes.items():
            c = {'id': nid, 'width': n['w'], 'height': n['h']}
            if n.get('ports'):
                c['layoutOptions'] = {'elk.portConstraints': 'FIXED_POS'}
                c['ports'] = [{'id': f'{nid}__W', 'x': 0, 'y': n['h'] / 2, 'width': 0, 'height': 0,
                               'layoutOptions': {'elk.port.side': 'WEST'}},
                              {'id': f'{nid}__E', 'x': n['w'], 'y': n['h'] / 2, 'width': 0, 'height': 0,
                               'layoutOptions': {'elk.port.side': 'EAST'}}]
            children.append(c)
        edges = []
        for i, e in enumerate(self.edges):
            src = f"{e['a']}__E" if self.nodes[e['a']].get('ports') else e['a']
            dst = f"{e['b']}__W" if self.nodes[e['b']].get('ports') else e['b']
            edges.append({'id': f'e{i}', 'sources': [src], 'targets': [dst]})
        graph = {'id': 'root', 'layoutOptions': self.opts, 'children': children, 'edges': edges}
        out = subprocess.run(['node', str(HERE / 'elk_layout.js')], input=json.dumps(graph), capture_output=True,
                             text=True, encoding='utf-8', check=True).stdout
        res = json.loads(out)
        for c in res['children']:
            self.nodes[c['id']].update(x=c['x'], y=c['y'])
        for e, r in zip(self.edges, sorted(res['edges'], key=lambda r: int(r['id'][1:]))):
            if e['straight'] and self.attr_straight:      # 속성 연결선: Chen 고전 표기처럼 중심-중심 직선
                e['pts'] = straight(self.nodes[e['a']], self.nodes[e['b']])
                continue
            s = r['sections'][0]
            e['pts'] = [(s['startPoint']['x'], s['startPoint']['y'])] + \
                       [(p['x'], p['y']) for p in s.get('bendPoints', [])] + \
                       [(s['endPoint']['x'], s['endPoint']['y'])]
        self.W, self.H = res['width'], res['height']

    # ---------------------------------------------------------------- 그리기
    def svg(self, title=''):
        out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {self.W:.0f} {self.H + (30 if title else 0):.0f}" '
               f'width="{self.W:.0f}" height="{self.H + (30 if title else 0):.0f}" font-family="{FONT}" font-size="{FS}">',
               '<rect width="100%" height="100%" fill="white"/>']
        dy = 30 if title else 0
        if title:
            out.append(f'<text x="12" y="20" font-size="15" font-weight="bold">{escape(title)}</text>')
        out.append(f'<g transform="translate(0,{dy})">')
        for e in self.edges:
            out += draw_edge(e, self.nodes)
        for n in self.nodes.values():
            out += draw_node(n)
        out.append('</g></svg>')
        return '\n'.join(out)


def boundary(n, dx, dy):
    """도형 중심에서 (dx,dy) 방향으로 나가는 반직선이 도형 경계와 만나는 지점까지의 비율"""
    hw, hh = n['w'] / 2, n['h'] / 2
    k = n['kind']
    if k == 'attr':
        return 1 / max(((dx / hw) ** 2 + (dy / hh) ** 2) ** 0.5, 1e-9)
    if k == 'rel':
        return 1 / max(abs(dx) / hw + abs(dy) / hh, 1e-9)
    if k == 'spec':
        return hw / max((dx * dx + dy * dy) ** 0.5, 1e-9)
    return min(hw / max(abs(dx), 1e-9), hh / max(abs(dy), 1e-9))


def straight(a, b):
    ax, ay = a['x'] + a['w'] / 2, a['y'] + a['h'] / 2
    bx, by = b['x'] + b['w'] / 2, b['y'] + b['h'] / 2
    dx, dy = bx - ax, by - ay
    ta, tb = boundary(a, dx, dy), boundary(b, -dx, -dy)
    return [(ax + dx * ta, ay + dy * ta), (bx - dx * tb, by - dy * tb)]


def poly(pts):
    return ' '.join(f'{x:.1f},{y:.1f}' for x, y in pts)


def draw_edge(e, nodes):
    pts, out = e['pts'], []
    if e['total']:
        out.append(f'<polyline points="{poly(pts)}" fill="none" stroke="#222" stroke-width="5"/>')
        out.append(f'<polyline points="{poly(pts)}" fill="none" stroke="white" stroke-width="2"/>')
    else:
        out.append(f'<polyline points="{poly(pts)}" fill="none" stroke="#222" stroke-width="1.3"/>')
    if e['subset']:
        (x1, y1), (x2, y2) = pts[-2], pts[-1]
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2
        L = max(((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5, 1e-6)
        ux, uy = (x2 - x1) / L, (y2 - y1) / L          # 하위 개체 쪽 방향
        nx, ny = -uy, ux
        s = (mx + 6 * nx - 3 * ux, my + 6 * ny - 3 * uy)
        t = (mx - 6 * nx - 3 * ux, my - 6 * ny - 3 * uy)
        c = (mx + 11 * ux, my + 11 * uy)
        out.append(f'<path d="M{s[0]:.1f},{s[1]:.1f} Q{c[0]:.1f},{c[1]:.1f} {t[0]:.1f},{t[1]:.1f}" '
                   f'fill="none" stroke="#222" stroke-width="1.5"/>')
    if e.get('label'):
        # 정의 속성 라벨은 특수화 원으로 들어가는 마지막 선분에 붙인다 (꺾인 선의 짧은 첫 선분은 다른 선과 겹치기 쉽다)
        (x1, y1), (x2, y2) = pts[-2], pts[-1]
        horiz = abs(x2 - x1) >= abs(y2 - y1)
        if horiz:
            lx, ly, anchor = (x2 - 6, y2 - 8, 'end') if x2 > x1 else (x2 + 6, y2 - 8, 'start')
        else:
            lx, ly, anchor = (x2 + 7, (y1 + y2) / 2 + 4, 'start')
        out.append(f'<text x="{lx:.1f}" y="{ly:.1f}" font-size="11" font-style="italic" fill="#225" '
                   f'text-anchor="{anchor}">{escape(e["label"])}</text>')
    if e['card']:
        if e['card_at'] == 'b':     # 마름모가 끝점 → 마지막 선분의 끝 근처
            (x1, y1), (x2, y2) = pts[-2], pts[-1]
            ax, ay, bx, by = x2, y2, x1, y1
        else:                       # 마름모가 시작점
            (x1, y1), (x2, y2) = pts[0], pts[1]
            ax, ay, bx, by = x1, y1, x2, y2
        L = max(((bx - ax) ** 2 + (by - ay) ** 2) ** 0.5, 1e-6)
        ux, uy = (bx - ax) / L, (by - ay) / L
        d = min(22, L / 2)
        px, py = ax + ux * d, ay + uy * d
        nx, ny = -uy, ux                      # 선에 수직인 방향 — 위쪽(수평선)·오른쪽(수직선)을 우선
        if ny > 0.1 or (abs(ny) <= 0.1 and nx < 0):
            nx, ny = -nx, -ny
        ox, oy = nx * 10, ny * 10 + 4
        out.append(f'<text x="{px + ox:.1f}" y="{py + oy:.1f}" font-size="12" font-weight="bold" '
                   f'text-anchor="middle" fill="#b00">{escape(e["card"])}</text>')
    return out


def draw_node(n):
    x, y, w, h, k = n['x'], n['y'], n['w'], n['h'], n['kind']
    cx, cy = x + w / 2, y + h / 2
    lab = escape(n['label'])
    out = []
    if k == 'entity':
        fill = '#eef2f7' if n.get('ref') else 'white'
        dash = ' stroke-dasharray="5,3"' if n.get('ref') else ''
        out.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" fill="{fill}" stroke="#222" stroke-width="1.4"{dash}/>')
        if n.get('weak'):
            out.append(f'<rect x="{x + 4:.1f}" y="{y + 4:.1f}" width="{w - 8:.1f}" height="{h - 8:.1f}" fill="none" stroke="#222" stroke-width="1.2"/>')
        out.append(f'<text x="{cx:.1f}" y="{cy + 4.5:.1f}" text-anchor="middle" font-weight="bold">{lab}</text>')
    elif k == 'rel':
        def diamond(i):
            return f'{cx:.1f},{y + i:.1f} {x + w - i * 1.6:.1f},{cy:.1f} {cx:.1f},{y + h - i:.1f} {x + i * 1.6:.1f},{cy:.1f}'
        out.append(f'<polygon points="{diamond(0)}" fill="white" stroke="#222" stroke-width="1.4"/>')
        if n.get('ident'):
            out.append(f'<polygon points="{diamond(5)}" fill="none" stroke="#222" stroke-width="1.2"/>')
        out.append(f'<text x="{cx:.1f}" y="{cy + 4.5:.1f}" text-anchor="middle">{lab}</text>')
    elif k == 'spec':
        out.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{w / 2:.1f}" fill="white" stroke="#222" stroke-width="1.4"/>')
        out.append(f'<text x="{cx:.1f}" y="{cy + 5:.1f}" text-anchor="middle" font-weight="bold">{lab}</text>')
    elif k == 'text':
        out.append(f'<text x="{cx:.1f}" y="{cy + 4:.1f}" text-anchor="middle" font-size="{n["size"]}" fill="#333">{lab}</text>')
    elif k == 'attr':
        dash = ' stroke-dasharray="4,3"' if n.get('derived') else ''
        out.append(f'<ellipse cx="{cx:.1f}" cy="{cy:.1f}" rx="{w / 2:.1f}" ry="{h / 2:.1f}" fill="white" stroke="#222" stroke-width="1.2"{dash}/>')
        if n.get('multi'):
            out.append(f'<ellipse cx="{cx:.1f}" cy="{cy:.1f}" rx="{w / 2 - 4:.1f}" ry="{h / 2 - 4:.1f}" fill="none" stroke="#222" stroke-width="1"/>')
        out.append(f'<text x="{cx:.1f}" y="{cy + 4.5:.1f}" text-anchor="middle" font-size="12">{lab}</text>')
        if n.get('key') or n.get('partial'):
            tw = text_w(n['label'], 12)
            dash = ' stroke-dasharray="3,2"' if n.get('partial') else ''
            out.append(f'<line x1="{cx - tw / 2:.1f}" y1="{cy + 7:.1f}" x2="{cx + tw / 2:.1f}" y2="{cy + 7:.1f}" stroke="#222" stroke-width="1"{dash}/>')
    return out


def render_png(svg: str, name: str, scale: float = 2.0) -> Path:
    """SVG → PNG (Edge 헤드리스 스크린샷). 한글 경로 문제를 피해 C:\\pgtemp\\render 에서 작업."""
    work = Path(r'C:\pgtemp\render')
    work.mkdir(parents=True, exist_ok=True)
    import re
    w, h = (float(v) for v in re.search(r'width="([\d.]+)" height="([\d.]+)"', svg).groups())
    src = work / f'{name}.html'
    src.write_text(f'<!doctype html><html><head><meta charset="utf-8"><style>html,body{{margin:0;padding:0;background:#fff}}'
                   f'svg{{display:block}}</style></head><body>{svg}</body></html>', encoding='utf-8')
    png = work / f'{name}.png'
    png.unlink(missing_ok=True)
    edge = r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'
    subprocess.run([edge, '--headless=new', '--disable-gpu', '--hide-scrollbars', f'--force-device-scale-factor={scale}',
                    f'--window-size={int(w) + 1},{int(h) + 1}', f'--screenshot={png}', src.as_uri()],
                   check=True, capture_output=True, timeout=120)
    dst = HERE / 'img' / f'{name}.png'
    dst.parent.mkdir(exist_ok=True)
    dst.write_bytes(png.read_bytes())
    (HERE / 'img' / f'{name}.svg').write_text(svg, encoding='utf-8')
    return dst
