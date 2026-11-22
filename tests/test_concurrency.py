"""동시성 검증: '보호' 전이와 아이템 이동이 같은 계정에서 겹칠 때.

실제로 연결 두 개를 열고, 한쪽 트랜잭션을 커밋하지 않은 채 다른 쪽을 실행해
잠금 대기가 일어나는지(pg_stat_activity), 끝난 뒤 결과가 일관적인지 확인한다.
"""
import threading
import time

import pytest
from psycopg import IsolationLevel, errors

from conftest import login, new_conn, transition, transfer, wait_until_blocked


def run_in_thread(fn):
    box = {}

    def target():
        try:
            box['value'] = fn()
        except Exception as exc:   # noqa: BLE001 — 스레드 예외를 본 스레드로 전달
            box['error'] = exc
    t = threading.Thread(target=target)
    t.start()
    return t, box


def owner_of(owner, item_id):
    return owner.execute('SELECT owner_account_id FROM ap.item WHERE item_id = %s', (item_id,)).fetchone()[0]


def in_snapshot(owner, case_id, item_id):
    return owner.execute('SELECT count(*) FROM ap.case_asset_snapshot WHERE case_id = %s AND item_id = %s',
                         (case_id, item_id)).fetchone()[0] == 1


# ---------------------------------------------------------------- 운영 함수: 어느 쪽이 먼저든 일관적
def test_transfer_waits_for_uncommitted_protect_then_is_rejected(game, owner, make_account):
    a, b = make_account(items=2), make_account(items=0)
    token = login(game, a)[1]
    item = a['items'][0]

    p = new_conn('ap_ops', 'p_protect')
    t = new_conn('ap_game', 't_transfer')
    try:
        case_id, *_ = transition(p, a['account_id'], 'PROTECTED')            # 커밋 전 — 계정 행 배타 잠금 보유
        thread, box = run_in_thread(lambda: (transfer(t, token, item, b['account_id']), t.commit())[0])
        assert wait_until_blocked(owner, 't_transfer'), '아이템 이동이 잠금 대기에 들어가야 한다'
        p.commit()
        thread.join(5)
    finally:
        p.close(), t.close()

    assert 'error' not in box, box.get('error')
    assert box['value'][1:] == ('REJECTED', 'SESSION_REVOKED')
    assert owner_of(owner, item) == a['account_id']
    assert in_snapshot(owner, case_id, item)


def test_protect_waits_for_uncommitted_transfer_and_snapshot_excludes_moved_item(game, owner, make_account):
    a, b = make_account(items=2), make_account(items=0)
    token = login(game, a)[1]
    item = a['items'][0]

    t = new_conn('ap_game', 't_transfer2')
    p = new_conn('ap_ops', 'p_protect2')
    try:
        assert transfer(t, token, item, b['account_id'])[1] == 'APPROVED'   # 커밋 전 — 계정 행 공유 잠금 보유
        thread, box = run_in_thread(lambda: (transition(p, a['account_id'], 'PROTECTED'), p.commit())[0])
        assert wait_until_blocked(owner, 'p_protect2'), '보호 전이가 잠금 대기에 들어가야 한다'
        t.commit()
        thread.join(5)
    finally:
        p.close(), t.close()

    assert 'error' not in box, box.get('error')
    case_id, _, _, _, revoked, snap = box['value']
    assert (revoked, snap) == (1, 1)                         # 옮겨진 아이템은 스냅샷에 없다
    assert owner_of(owner, item) == b['account_id']
    assert not in_snapshot(owner, case_id, item)


# ---------------------------------------------------------------- 실험용 취약 함수: 잠금이 없으면 생기는 일
def _race_nolock(owner, game, make_account, isolation):
    """취약 함수가 검사를 끝내고 지연(1.5초)하는 동안 보호 전이를 커밋한다."""
    a, b = make_account(items=2), make_account(items=0)
    token = login(game, a)[1]
    item = a['items'][0]

    t = new_conn('ap_owner', 't_nolock')
    t.isolation_level = isolation
    p = new_conn('ap_ops', 'p_race')
    p.isolation_level = isolation
    try:
        thread, box = run_in_thread(lambda: (t.execute('SELECT * FROM lab.transfer_item_nolock(%s, %s, %s, 1500)',
                                                       (token, item, b['account_id'])).fetchone(), t.commit())[0])
        time.sleep(0.5)                                        # 취약 함수가 '정상' 상태를 확인한 뒤
        case_id, *_ = transition(p, a['account_id'], 'PROTECTED')
        p.commit()                                             # 보호 전이 커밋 (기다림 없이 바로 끝난다)
        thread.join(10)
    finally:
        p.close(), t.close()
    return a, b, item, case_id, box


@pytest.mark.parametrize('isolation', [IsolationLevel.READ_COMMITTED, IsolationLevel.REPEATABLE_READ])
def test_without_lock_write_skew_happens(owner, game, make_account, isolation):
    a, b, item, case_id, box = _race_nolock(owner, game, make_account, isolation)
    assert 'error' not in box, box.get('error')
    assert box['value'][1] == 'APPROVED'                      # 보호 이후에 이동이 승인됐고
    assert owner_of(owner, item) == b['account_id']            # 실제 소유자는 바뀌었는데
    assert in_snapshot(owner, case_id, item)                   # 스냅샷은 '보유 중'이라고 기록 → 어느 직렬 순서로도 불가능


def test_serializable_aborts_one_side(owner, game, make_account):
    a, b, item, case_id, box = _race_nolock(owner, game, make_account, IsolationLevel.SERIALIZABLE)
    assert isinstance(box.get('error'), errors.SerializationFailure)   # 늦게 끝난 이동 쪽이 취소된다
    assert owner_of(owner, item) == a['account_id']
    assert in_snapshot(owner, case_id, item)
