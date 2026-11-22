"""phys_catalog.json(실제 DB 카탈로그) → docs/ERD.md (Mermaid ER 다이어그램, GitHub에서 바로 렌더링).

    python scripts/export_physical_json.py    # 먼저 카탈로그를 DB에서 다시 뽑는다
    python scripts/export_erd_mermaid.py

표기: 실선 = 식별 관계(외래키가 기본키의 일부), 점선 = 비식별 관계.
부모 쪽 || = 반드시 1개, |o = 0 또는 1개(외래키 NULL 허용). 자식 쪽 o{ = 0개 이상, o| = 0 또는 1개(외래키가 유일).
"""
import json
import sys

from dbconf import ROOT

CATALOG = ROOT / 'docs' / 'spec' / 'phys_catalog.json'


def relationships(cat):
    lines = []
    for child, t in cat.items():
        notnull = {c['name']: c['notnull'] for c in t['columns']}
        generated = {c['name'] for c in t['columns'] if c['generated']}
        pk = next(k['cols'] for k in t['constraints'] if k['type'] == 'p')
        uniques = [set(k['cols']) for k in t['constraints'] if k['type'] in ('p', 'u')]
        for fk in (k for k in t['constraints'] if k['type'] == 'f'):
            cols = set(fk['cols'])
            parent_side = '||' if all(notnull[c] for c in cols) else '|o'
            child_side = 'o|' if any(u <= cols for u in uniques) else 'o{'          # 키를 포함하면 자식은 최대 1개
            # 식별 관계: 생성 컬럼(고정값 판별자)을 뺀 외래키가 기본키 안에 있다 (burst_signal 의 rule_code 등)
            line = '--' if cols - generated <= set(pk) else '..'
            lines.append(f'    {fk["ref"]} {parent_side}{line}{child_side} {child} : "{", ".join(fk["cols"])}"')
    return lines


def entities(cat):
    out = []
    for name, t in cat.items():
        cons = t['constraints']
        pk = next(k['cols'] for k in cons if k['type'] == 'p')
        fk_cols = {c for k in cons if k['type'] == 'f' for c in k['cols']}
        uk_cols = {c for k in cons if k['type'] == 'u' for c in k['cols']}
        out.append(f'    {name} {{')
        for c in t['columns']:
            keys = [k for k, cols in (('PK', pk), ('FK', fk_cols), ('UK', uk_cols)) if c['name'] in cols]
            notes = [n for n, on in (('NULL 허용', not c['notnull']), ('IDENTITY', c['identity']),
                                     ('생성 컬럼', c['generated'])) if on]
            line = f'        {c["type"].replace(" ", "_")} {c["name"]}'
            if keys:
                line += ' ' + ', '.join(keys)
            if notes:
                line += f' "{", ".join(notes)}"'
            out.append(line)
        out.append('    }')
    return out


def main() -> int:
    cat = json.loads(CATALOG.read_text(encoding='utf-8'))
    counts = {k: sum(1 for t in cat.values() for c in t['constraints'] if c['type'] == k) for k in 'pfuc'}
    partial = sum(len(t['partial_uniques']) for t in cat.values())
    doc = [
        '# ERD (물리 스키마)',
        '',
        '`scripts/export_erd_mermaid.py`가 실제 DB 카탈로그(`docs/spec/phys_catalog.json`)에서 만든다. 손으로 그리지 않는다.',
        '',
        f'테이블 {len(cat)}개 · PK {counts["p"]} · FK {counts["f"]} · UNIQUE {counts["u"]} + 부분 UNIQUE {partial} · CHECK {counts["c"]}',
        '',
        '실선은 식별 관계(외래키가 기본키의 일부), 점선은 비식별 관계다.',
        '',
        '## 관계만',
        '',
        '```mermaid',
        'erDiagram',
        *relationships(cat),
        '```',
        '',
        '## 컬럼 포함',
        '',
        '```mermaid',
        'erDiagram',
        *relationships(cat),
        *entities(cat),
        '```',
        '',
    ]
    path = ROOT / 'docs' / 'ERD.md'
    path.write_text('\n'.join(doc), encoding='utf-8')
    print(f'wrote {path.relative_to(ROOT)}: {len(cat)} tables, {counts["f"]} relationships')
    return 0


if __name__ == '__main__':
    sys.exit(main())
