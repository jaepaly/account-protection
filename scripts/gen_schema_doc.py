"""DB 카탈로그에서 논리설계 표(관계 스키마, PK/FK, 제약조건)를 뽑아 docs/schema_catalog.md 로 쓴다.

손으로 옮겨 적지 않고 실제 DB에서 읽기 때문에, 문서와 구현이 어긋나지 않는다.
    python scripts/gen_schema_doc.py
"""
import sys

from dbconf import ROOT, connect, db_name

ORDER = ['protection_state', 'allowed_transition', 'operator', 'account', 'credential_history', 'device',
         'account_device', 'game_session', 'login_attempt', 'risk_rule', 'risk_signal', 'burst_signal', 'protection_case',
         'case_transition', 'case_asset_snapshot', 'item_template', 'item', 'item_transfer']


def main() -> int:
    with connect('ap_owner', db_name('dev')) as conn:
        cols = conn.execute("""
            SELECT c.relname, a.attname, format_type(a.atttypid, a.atttypmod), a.attnotnull, a.attnum
              FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid
              JOIN pg_namespace n ON n.oid = c.relnamespace
             WHERE n.nspname = 'ap' AND c.relkind = 'r' AND a.attnum > 0 AND NOT a.attisdropped
             ORDER BY c.relname, a.attnum""").fetchall()
        cons = conn.execute("""
            SELECT c.relname, k.conname, k.contype,
                   ARRAY(SELECT a.attname FROM unnest(k.conkey) WITH ORDINALITY u(n, i)
                         JOIN pg_attribute a ON a.attrelid = k.conrelid AND a.attnum = u.n ORDER BY u.i),
                   rc.relname,
                   ARRAY(SELECT a.attname FROM unnest(k.confkey) WITH ORDINALITY u(n, i)
                         JOIN pg_attribute a ON a.attrelid = k.confrelid AND a.attnum = u.n ORDER BY u.i),
                   k.condeferrable, pg_get_constraintdef(k.oid)
              FROM pg_constraint k JOIN pg_class c ON c.oid = k.conrelid
              JOIN pg_namespace n ON n.oid = c.relnamespace
              LEFT JOIN pg_class rc ON rc.oid = k.confrelid
             WHERE n.nspname = 'ap'
             ORDER BY c.relname, k.contype, k.conname""").fetchall()
        idx = conn.execute("""
            SELECT t.relname, i.relname, pg_get_indexdef(x.indexrelid)
              FROM pg_index x JOIN pg_class i ON i.oid = x.indexrelid JOIN pg_class t ON t.oid = x.indrelid
              JOIN pg_namespace n ON n.oid = t.relnamespace
             WHERE n.nspname = 'ap' AND NOT x.indisprimary
               AND NOT EXISTS (SELECT 1 FROM pg_constraint k WHERE k.conindid = x.indexrelid)
             ORDER BY t.relname, i.relname""").fetchall()
        trig = conn.execute("""
            SELECT c.relname, t.tgname, t.tgdeferrable
              FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid JOIN pg_namespace n ON n.oid = c.relnamespace
             WHERE n.nspname = 'ap' AND NOT t.tgisinternal ORDER BY 1, 2""").fetchall()

    by_table = {}
    for t, name, typ, notnull, _ in cols:
        by_table.setdefault(t, []).append((name, typ, notnull))
    pk, fks, uqs, checks = {}, {}, {}, {}
    for t, name, ctype, keys, ref, refkeys, deferrable, definition in cons:
        if ctype == 'p':
            pk[t] = keys
        elif ctype == 'f':
            fks.setdefault(t, []).append((keys, ref, refkeys, deferrable))
        elif ctype == 'u':
            uqs.setdefault(t, []).append(keys)
        elif ctype == 'c':
            checks.setdefault(t, []).append((name, definition))

    out = ['# 논리설계 — 관계 스키마 (DB 카탈로그에서 자동 생성)', '',
           '표기: **굵게** = 기본키(PK), *기울임* = 외래키(FK), ***굵은 기울임*** = PK이면서 FK, `UQ` = 유니크, `?` = NULL 허용.', '']
    out += ['## 관계 스키마', '']
    for t in ORDER:
        fk_cols = {c for keys, *_ in fks.get(t, []) for c in keys}
        uq_cols = {keys[0] for keys in uqs.get(t, []) if len(keys) == 1}
        parts = []
        for name, typ, notnull in by_table[t]:
            in_pk, in_fk = name in pk.get(t, []), name in fk_cols
            label = f'***{name}***' if in_pk and in_fk else f'**{name}**' if in_pk else f'*{name}*' if in_fk else name
            if name in uq_cols:
                label += ' `UQ`'
            if not notnull:
                label += '?'
            parts.append(label)
        out.append(f'- **{t}**({", ".join(parts)})')
    out += ['', '## 외래키', '', '| 테이블 | 컬럼 | → 참조 테이블(컬럼) | 비고 |', '|---|---|---|---|']
    for t in ORDER:
        for keys, ref, refkeys, deferrable in fks.get(t, []):
            note = '커밋 시점 검사 (DEFERRABLE)' if deferrable else ''
            out.append(f'| {t} | {", ".join(keys)} | {ref}({", ".join(refkeys)}) | {note} |')
    out += ['', '## 복합 유니크 · 부분 유니크', '']
    for t in ORDER:
        for keys in uqs.get(t, []):
            if len(keys) > 1:
                out.append(f'- {t}: UNIQUE({", ".join(keys)})')
    for t, name, definition in idx:
        if 'UNIQUE' in definition:
            out.append(f'- {t}: `{definition.split(" USING ")[1]}` ({name})')
    out += ['', '## CHECK 제약', '']
    for t in ORDER:
        for name, definition in checks.get(t, []):
            out.append(f'- {t}.{name}: `{definition}`')
    out += ['', '## 보조 인덱스', '']
    for t, name, definition in idx:
        if 'UNIQUE' not in definition:
            out.append(f'- {t}: `{definition.split(" USING ")[1]}`')
    out += ['', '## 트리거', '']
    for t, name, deferrable in trig:
        out.append(f'- {t}.{name}' + (' (지연 제약 트리거)' if deferrable else ''))

    path = ROOT / 'docs' / 'schema_catalog.md'
    path.write_text('\n'.join(out) + '\n', encoding='utf-8')
    print(f'wrote {path.relative_to(ROOT)} ({len(ORDER)} tables)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
