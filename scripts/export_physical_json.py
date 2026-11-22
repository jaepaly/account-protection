"""DB 카탈로그 → docs/spec/phys_catalog.json (물리 설계 문서용: 컬럼·제약·FK 동작).

    PG_PORT=5499 python scripts/export_physical_json.py
"""
import json
import re
import sys

from dbconf import ROOT, connect, db_name
from export_catalog_json import ORDER

TYPE = [(r'^character varying', 'varchar'), (r'^character\(', 'char('), (r'^timestamp with time zone$', 'timestamptz')]
ACTION = {'a': 'NO ACTION', 'r': 'RESTRICT', 'c': 'CASCADE', 'n': 'SET NULL', 'd': 'SET DEFAULT'}


def short_type(t: str) -> str:
    for pat, rep in TYPE:
        t = re.sub(pat, rep, t)
    return t


def short_default(d: str | None) -> str | None:
    return re.sub(r'::[a-z ]+(\(\d+\))?', '', d) if d else d      # 'NORMAL'::character varying → 'NORMAL'


def main() -> int:
    with connect('ap_owner', db_name('dev'), connect_timeout=10) as conn:
        triggers = conn.execute("""
            SELECT c.relname, g.tgname, g.tgconstraint <> 0, g.tgdeferrable AND g.tginitdeferred
              FROM pg_trigger g JOIN pg_class c ON c.oid = g.tgrelid JOIN pg_namespace n ON n.oid = c.relnamespace
             WHERE n.nspname = 'ap' AND NOT g.tgisinternal ORDER BY 1, 2""").fetchall()
        cols = conn.execute("""
            SELECT c.relname, a.attname, format_type(a.atttypid, a.atttypmod), a.attnotnull,
                   pg_get_expr(d.adbin, d.adrelid), a.attidentity <> '', a.attgenerated = 's'
              FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid
              JOIN pg_namespace n ON n.oid = c.relnamespace
              LEFT JOIN pg_attrdef d ON d.adrelid = a.attrelid AND d.adnum = a.attnum
             WHERE n.nspname = 'ap' AND c.relkind = 'r' AND a.attnum > 0 AND NOT a.attisdropped
             ORDER BY c.relname, a.attnum""").fetchall()
        cons = conn.execute("""
            SELECT c.relname, k.conname, k.contype,
                   ARRAY(SELECT a.attname FROM unnest(k.conkey) WITH ORDINALITY u(n, i)
                         JOIN pg_attribute a ON a.attrelid = k.conrelid AND a.attnum = u.n ORDER BY u.i),
                   rc.relname,
                   ARRAY(SELECT a.attname FROM unnest(k.confkey) WITH ORDINALITY u(n, i)
                         JOIN pg_attribute a ON a.attrelid = k.confrelid AND a.attnum = u.n ORDER BY u.i),
                   k.confdeltype, k.confupdtype, k.condeferrable, k.condeferred, pg_get_constraintdef(k.oid)
              FROM pg_constraint k JOIN pg_class c ON c.oid = k.conrelid
              JOIN pg_namespace n ON n.oid = c.relnamespace
              LEFT JOIN pg_class rc ON rc.oid = k.confrelid
             WHERE n.nspname = 'ap' AND k.contype IN ('p', 'f', 'u', 'c')
             ORDER BY c.relname, k.contype, k.conname""").fetchall()
        partial = conn.execute("""
            SELECT t.relname, i.relname, pg_get_indexdef(x.indexrelid)
              FROM pg_index x JOIN pg_class t ON t.oid = x.indrelid JOIN pg_class i ON i.oid = x.indexrelid
              JOIN pg_namespace n ON n.oid = t.relnamespace
             WHERE n.nspname = 'ap' AND x.indisunique AND x.indpred IS NOT NULL""").fetchall()

    out = {t: {'columns': [], 'constraints': [], 'partial_uniques': [], 'triggers': []} for t in ORDER}
    for t, name, typ, notnull, default, identity, generated in cols:
        out[t]['columns'].append({'name': name, 'type': short_type(typ), 'notnull': notnull,
                                  'default': None if identity or generated else short_default(default),
                                  'identity': identity, 'generated': generated})
    for t, name, ctype, keys, ref, refkeys, dele, upd, deferrable, deferred, definition in cons:
        row = {'name': name, 'type': ctype, 'cols': keys, 'def': definition}
        if ctype == 'f':
            row.update(ref=ref, refcols=refkeys, on_delete=ACTION[dele], on_update=ACTION[upd],
                       deferred=bool(deferrable and deferred))
        out[t]['constraints'].append(row)
    for t, name, is_constraint, deferred in triggers:
        out[t]['triggers'].append({'name': name, 'constraint': is_constraint, 'deferred': deferred})
    for t, name, definition in partial:
        out[t]['partial_uniques'].append({'name': name, 'def': definition.split(' USING btree ')[1]})

    path = ROOT / 'docs' / 'spec' / 'phys_catalog.json'
    path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding='utf-8')
    n = lambda k: sum(1 for v in out.values() for c in v['constraints'] if c['type'] == k)
    print(f'wrote {path.relative_to(ROOT)}: {len(out)} tables, {sum(len(v["columns"]) for v in out.values())} columns, '
          f'PK {n("p")} / FK {n("f")} / UK {n("u")} + 부분 {sum(len(v["partial_uniques"]) for v in out.values())} / CK {n("c")}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
