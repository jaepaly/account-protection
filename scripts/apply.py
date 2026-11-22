"""DB 생성 및 SQL 파일 적용.

    python scripts/apply.py                 # 개발 DB에 적용 (이미 있으면 건너뜀)
    python scripts/apply.py --reset         # 개발 DB를 지우고 처음부터
    python scripts/apply.py --target test   # 테스트 DB (항상 새로 만든다)
    python scripts/apply.py --reset --lab   # 실험용(lab/) 함수까지 적용

관리자(postgres) 계정은 ① 프로젝트 역할 생성 ② 데이터베이스 생성에만 쓴다.
스키마·함수·데이터는 전부 ap_owner 로 적용한다.
"""
import argparse
import sys

from psycopg import sql

from dbconf import ROOT, ENV, ROLE_PASSWORD_KEY, connect, db_name

SQL_FILES = ['01_schema.sql', '02_functions.sql', '03_views.sql', '04_grants.sql', '05_reference_data.sql']


def ensure_roles_and_database(dbname: str, reset: bool) -> None:
    with connect('superuser', 'postgres', autocommit=True) as conn:
        for role, key in ROLE_PASSWORD_KEY.items():
            exists = conn.execute('SELECT 1 FROM pg_roles WHERE rolname = %s', (role,)).fetchone()
            verb = 'ALTER' if exists else 'CREATE'
            conn.execute(sql.SQL(verb + ' ROLE {} LOGIN PASSWORD {}').format(
                sql.Identifier(role), sql.Literal(ENV[key])))
        conn.execute('GRANT pg_read_all_stats TO ap_owner')   # 실험 중 잠금 대기 관찰(pg_stat_activity)용
        exists = conn.execute('SELECT 1 FROM pg_database WHERE datname = %s', (dbname,)).fetchone()
        if exists and reset:
            conn.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(dbname)))
            exists = None
        if not exists:
            conn.execute(sql.SQL("CREATE DATABASE {} OWNER ap_owner TEMPLATE template0 ENCODING 'UTF8'").format(
                sql.Identifier(dbname)))
            print(f'database {dbname} created')


def apply_files(dbname: str, files: list) -> None:
    with connect('ap_owner', dbname) as conn:
        if conn.execute("SELECT 1 FROM pg_namespace WHERE nspname = 'ap'").fetchone():
            print(f'schema ap already exists in {dbname} — skipped (use --reset to rebuild)')
            return
        conn.execute(sql.SQL('REVOKE CONNECT ON DATABASE {} FROM PUBLIC').format(sql.Identifier(dbname)))
        conn.execute(sql.SQL('GRANT CONNECT ON DATABASE {} TO ap_ops, ap_game').format(sql.Identifier(dbname)))
        conn.execute('GRANT USAGE, CREATE ON SCHEMA public TO ap_ops')   # Django 자체 테이블용
        conn.commit()
        for path in files:
            conn.execute(path.read_text(encoding='utf-8'))
            conn.commit()
            print(f'applied {path.relative_to(ROOT)}')


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--target', choices=['dev', 'test'], default='dev')
    parser.add_argument('--reset', action='store_true')
    parser.add_argument('--lab', action='store_true', help='lab/*.sql (실험용 취약 함수) 도 적용')
    args = parser.parse_args()

    dbname = db_name(args.target)
    reset = args.reset or args.target == 'test'
    files = [ROOT / 'db' / f for f in SQL_FILES]
    if args.lab or args.target == 'test':
        files += sorted((ROOT / 'lab').glob('*.sql'))

    ensure_roles_and_database(dbname, reset)
    apply_files(dbname, files)
    return 0


if __name__ == '__main__':
    sys.exit(main())
