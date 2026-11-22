"""DB 카탈로그 → docs/spec/norm_catalog.json (정규화 문서의 최종 테이블 목록용).

    PG_PORT=5499 python scripts/export_catalog_json.py
"""
import json
import sys

from dbconf import ROOT, connect, db_name

ORDER = ['protection_state', 'allowed_transition', 'operator', 'account', 'credential_history', 'device',
         'account_device', 'game_session', 'login_attempt', 'risk_rule', 'risk_signal', 'burst_signal',
         'protection_case', 'case_transition', 'case_asset_snapshot', 'item_template', 'item', 'item_transfer']


def main() -> int:
    with connect('ap_owner', db_name('dev')) as conn:
        cols = conn.execute("""
            SELECT c.relname, a.attname, format_type(a.atttypid, a.atttypmod), a.attnotnull, a.attgenerated = 's'
              FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid
              JOIN pg_namespace n ON n.oid = c.relnamespace
             WHERE n.nspname = 'ap' AND c.relkind = 'r' AND a.attnum > 0 AND NOT a.attisdropped
             ORDER BY c.relname, a.attnum""").fetchall()
        cons = conn.execute("""
            SELECT c.relname, k.contype,
                   ARRAY(SELECT a.attname FROM unnest(k.conkey) WITH ORDINALITY u(n, i)
                         JOIN pg_attribute a ON a.attrelid = k.conrelid AND a.attnum = u.n ORDER BY u.i),
                   rc.relname,
                   ARRAY(SELECT a.attname FROM unnest(k.confkey) WITH ORDINALITY u(n, i)
                         JOIN pg_attribute a ON a.attrelid = k.confrelid AND a.attnum = u.n ORDER BY u.i)
              FROM pg_constraint k JOIN pg_class c ON c.oid = k.conrelid
              JOIN pg_namespace n ON n.oid = c.relnamespace
              LEFT JOIN pg_class rc ON rc.oid = k.confrelid
             WHERE n.nspname = 'ap' AND k.contype IN ('p', 'f', 'u')
             ORDER BY c.relname, k.contype, k.conname""").fetchall()
        partial = conn.execute("""
            SELECT t.relname, pg_get_indexdef(x.indexrelid)
              FROM pg_index x JOIN pg_class t ON t.oid = x.indrelid JOIN pg_namespace n ON n.oid = t.relnamespace
             WHERE n.nspname = 'ap' AND x.indisunique AND x.indpred IS NOT NULL""").fetchall()

    out = {t: {'columns': [], 'pk': [], 'fks': [], 'uniques': [], 'partial_uniques': []} for t in ORDER}
    for t, name, typ, notnull, generated in cols:
        out[t]['columns'].append({'name': name, 'type': typ, 'notnull': notnull, 'generated': generated})
    for t, ctype, keys, ref, refkeys in cons:
        if ctype == 'p':
            out[t]['pk'] = keys
        elif ctype == 'f':
            out[t]['fks'].append({'cols': keys, 'ref': ref, 'refcols': refkeys})
        else:
            out[t]['uniques'].append(keys)
    for t, definition in partial:
        out[t]['partial_uniques'].append(definition.split(' USING btree ')[1])
    path = ROOT / 'docs' / 'spec' / 'norm_catalog.json'
    path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding='utf-8')
    print(f'wrote {path.relative_to(ROOT)}: {len(out)} tables, {sum(len(v["columns"]) for v in out.values())} columns')
    return 0


if __name__ == '__main__':
    sys.exit(main())
