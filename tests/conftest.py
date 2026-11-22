"""테스트 공통 설정 — 매 실행마다 테스트 DB(account_protection_test)를 새로 만든다."""
import itertools
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import apply  # noqa: E402
from dbconf import ROOT, connect, db_name  # noqa: E402

TEST_DB = db_name('test')
_seq = itertools.count(1)


@pytest.fixture(scope='session', autouse=True)
def fresh_test_db():
    apply.ensure_roles_and_database(TEST_DB, reset=True)
    files = [ROOT / 'db' / f for f in apply.SQL_FILES] + sorted((ROOT / 'lab').glob('*.sql'))
    apply.apply_files(TEST_DB, files)


@pytest.fixture
def owner():
    with connect('ap_owner', TEST_DB, autocommit=True) as conn:
        yield conn


@pytest.fixture
def ops():
    with connect('ap_ops', TEST_DB, autocommit=True) as conn:
        yield conn


@pytest.fixture
def game():
    with connect('ap_game', TEST_DB, autocommit=True) as conn:
        yield conn


def new_conn(role, name):
    return connect(role, TEST_DB, application_name=name)


@pytest.fixture
def make_account(owner):
    """계정 + 초기 자격증명 이력 + 신뢰 기기 1개 + 아이템 n개를 만든다 (소유자 권한으로 직접 삽입)."""
    def _make(password='correct-horse-1', items=3, tradable=True):
        n = next(_seq)
        login_id = f'tester{n:04d}'
        device_key = f'trusted-device-{login_id}'
        with owner.transaction():   # account ↔ credential_history 순환 FK 는 커밋 시점에 검사
            acc_id = owner.execute(
                """INSERT INTO ap.account (login_id, nickname, email, password_hash)
                   VALUES (%s, %s, %s, ext.crypt(%s, ext.gen_salt('bf', 4))) RETURNING account_id""",
                (login_id, f'닉네임{n}', f'{login_id}@example.com', password)).fetchone()[0]
            owner.execute("INSERT INTO ap.credential_history (account_id, version, reason) VALUES (%s, 1, 'INITIAL')",
                          (acc_id,))
            dev_id = owner.execute(
                """INSERT INTO ap.device (fingerprint, platform)
                   VALUES (encode(ext.digest(%s, 'sha256'), 'hex'), 'ANDROID') RETURNING device_id""",
                (device_key,)).fetchone()[0]
            owner.execute("""INSERT INTO ap.account_device (account_id, device_id, trusted_at)
                             VALUES (%s, %s, now())""", (acc_id, dev_id))
            tpl = owner.execute('SELECT template_id FROM ap.item_template WHERE is_tradable = %s ORDER BY template_id LIMIT 1',
                                (tradable,)).fetchone()[0]
            item_ids = [owner.execute('INSERT INTO ap.item (template_id, owner_account_id) VALUES (%s, %s) RETURNING item_id',
                                      (tpl, acc_id)).fetchone()[0] for _ in range(items)]
        return {'account_id': acc_id, 'login_id': login_id, 'password': password,
                'device_key': device_key, 'items': item_ids}
    return _make


def login(game_conn, acc, password=None, device_key=None, ip='10.0.0.1'):
    return game_conn.execute('SELECT * FROM ap.login(%s, %s, %s, %s, %s)',
                             (acc['login_id'], password or acc['password'], device_key or acc['device_key'],
                              'ANDROID', ip)).fetchone()


def transition(conn, account_id, to_state, operator_id=1, reason='테스트'):
    return conn.execute('SELECT * FROM ap.transition_account(%s, %s, %s, %s)',
                        (account_id, to_state, operator_id, reason)).fetchone()


def transfer(conn, token, item_id, to_account_id):
    return conn.execute('SELECT * FROM ap.transfer_item(%s, %s, %s)', (token, item_id, to_account_id)).fetchone()


def wait_until_blocked(observer, application_name, timeout=5.0):
    """다른 연결이 잠금 대기(wait_event_type = 'Lock')에 들어갈 때까지 기다린다."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        row = observer.execute("""SELECT 1 FROM pg_stat_activity
                                  WHERE application_name = %s AND wait_event_type = 'Lock'""",
                               (application_name,)).fetchone()
        if row:
            return True
        time.sleep(0.05)
    return False
