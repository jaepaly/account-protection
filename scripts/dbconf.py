"""접속 설정 공통 모듈 — .env 를 읽고, 역할별 접속을 만든다.

환경변수가 있으면 .env 보다 우선한다 (예: PG_PORT=5499 로 다른 서버에 적용).
"""
import os
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parents[1]


def load_env() -> dict:
    env = {}
    path = ROOT / '.env'
    if path.exists():
        for line in path.read_text(encoding='utf-8').splitlines():
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            key, value = line.split('=', 1)
            env[key.strip()] = value.strip()
    env.update({k: v for k, v in os.environ.items() if k.startswith(('PG_', 'AP_'))})
    return env


ENV = load_env()

ROLE_PASSWORD_KEY = {
    'ap_owner': 'AP_OWNER_PASSWORD',
    'ap_ops': 'AP_OPS_PASSWORD',
    'ap_game': 'AP_GAME_PASSWORD',
}


def db_name(target: str = 'dev') -> str:
    return ENV['PG_TEST_DB'] if target == 'test' else ENV['PG_DB']


def connect(role: str, dbname: str, autocommit: bool = False, **kwargs) -> psycopg.Connection:
    """role: 'superuser' | 'ap_owner' | 'ap_ops' | 'ap_game'"""
    if role == 'superuser':
        user, password = ENV.get('PG_SUPERUSER', 'postgres'), ENV.get('PG_SUPERUSER_PASSWORD', '')
    else:
        user, password = role, ENV[ROLE_PASSWORD_KEY[role]]
    return psycopg.connect(host=ENV.get('PG_HOST', '127.0.0.1'), port=int(ENV.get('PG_PORT', 5433)),
                           user=user, password=password or None, dbname=dbname,
                           autocommit=autocommit, client_encoding='utf8', **kwargs)
