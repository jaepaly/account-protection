"""정책 검증: 로그인·탐지·상태 전이·아이템 이동·복구·권한·트리거."""
import pytest
from psycopg import errors

from conftest import login, transition, transfer


def account_row(owner, account_id):
    return owner.execute("""SELECT state_code, credential_version, password_hash IS NULL
                            FROM ap.account WHERE account_id = %s""", (account_id,)).fetchone()


def signals(owner, account_id, rule):
    """(실패 폭주 세부 실패 횟수 또는 None, 연결된 케이스) 목록"""
    return owner.execute("""SELECT bs.failures_in_window, rs.case_id FROM ap.risk_signal rs
                            JOIN ap.login_attempt la ON la.attempt_id = rs.trigger_attempt_id
                            LEFT JOIN ap.burst_signal bs ON bs.signal_id = rs.signal_id
                            WHERE la.account_id = %s AND rs.rule_code = %s ORDER BY rs.signal_id""",
                         (account_id, rule)).fetchall()


# ---------------------------------------------------------------- 로그인
def test_login_issues_session_and_stores_only_token_hash(game, owner, make_account):
    acc = make_account()
    result, token, _ = login(game, acc)
    assert result == 'OK' and len(token) == 64
    version, revoked = owner.execute("""SELECT issued_credential_version, revoked_at FROM ap.game_session
                                        WHERE account_id = %s""", (acc['account_id'],)).fetchone()
    assert (version, revoked) == (1, None)
    assert owner.execute('SELECT count(*) FROM ap.game_session WHERE token_hash = %s', (token,)).fetchone()[0] == 0


def test_bad_password_is_recorded_without_session(game, owner, make_account):
    acc = make_account()
    assert login(game, acc, password='wrong')[:2] == ('BAD_PASSWORD', None)
    assert owner.execute("""SELECT count(*) FROM ap.login_attempt
                            WHERE account_id = %s AND NOT success AND failure_reason = 'BAD_PASSWORD'""",
                         (acc['account_id'],)).fetchone()[0] == 1


def test_unknown_login_id_does_not_reveal_existence(game):
    row = game.execute("SELECT * FROM ap.login('nobody', 'x', 'dev', 'OTHER', '10.0.0.9')").fetchone()
    assert row == ('INVALID_CREDENTIALS', None, None)


# ---------------------------------------------------------------- 탐지
def test_failed_burst_raises_exactly_one_signal(game, owner, make_account):
    acc = make_account()
    for _ in range(7):
        login(game, acc, password='wrong', device_key='attacker-box', ip='203.0.113.7')
    found = signals(owner, acc['account_id'], 'FAILED_BURST')
    assert len(found) == 1
    assert found[0][0] == 5                                   # 하위 타입 burst_signal 에 원자값으로 저장


def test_new_device_signal_only_on_first_login_from_untrusted_device(game, owner, make_account):
    acc = make_account()
    login(game, acc)                                  # 신뢰 기기
    assert signals(owner, acc['account_id'], 'NEW_DEVICE') == []
    login(game, acc, device_key='stolen-pc')          # 처음 보는 기기
    login(game, acc, device_key='stolen-pc')
    assert len(signals(owner, acc['account_id'], 'NEW_DEVICE')) == 1


# ---------------------------------------------------------------- 상태 전이
def test_disallowed_transition_is_rejected(ops, make_account):
    acc = make_account()
    with pytest.raises(errors.RaiseException, match='TRANSITION_NOT_ALLOWED: NORMAL -> RECOVERING'):
        transition(ops, acc['account_id'], 'RECOVERING')


def test_reason_is_required(ops, make_account):
    acc = make_account()
    with pytest.raises(errors.RaiseException, match='REASON_REQUIRED'):
        transition(ops, acc['account_id'], 'SUSPECTED', reason='  ')


def test_protect_revokes_sessions_rotates_credential_and_snapshots_items(game, ops, owner, make_account):
    acc = make_account(items=3)
    aid = acc['account_id']
    login(game, acc)
    login(game, acc, device_key='stolen-pc', ip='198.51.100.4')

    case_id, seq, frm, to, revoked, snap = transition(ops, aid, 'SUSPECTED', reason='신규 기기 로그인 확인')
    assert (seq, frm, to, revoked, snap) == (1, 'NORMAL', 'SUSPECTED', 0, 0)
    assert [c for _, c in signals(owner, aid, 'NEW_DEVICE')] == [case_id]     # 미처리 신호가 케이스에 연결

    case2, seq, frm, to, revoked, snap = transition(ops, aid, 'PROTECTED', reason='탈취 판단')
    assert (case2, seq, revoked, snap) == (case_id, 2, 2, 3)
    assert account_row(owner, aid) == ('PROTECTED', 2, True)
    assert owner.execute("""SELECT count(*) FROM ap.game_session
                            WHERE account_id = %s AND revoked_case_id = %s AND revoked_seq = 2""",
                         (aid, case_id)).fetchone()[0] == 2
    assert owner.execute("""SELECT reason FROM ap.credential_history WHERE account_id = %s AND version = 2""",
                         (aid,)).fetchone()[0] == 'FORCED_ROTATION'
    assert login(game, acc)[0] == 'STATE_BLOCKED'


def test_recovery_requires_new_password_then_closes_case(game, ops, owner, make_account):
    acc = make_account()
    aid = acc['account_id']
    transition(ops, aid, 'PROTECTED')
    transition(ops, aid, 'RECOVERING')
    with pytest.raises(errors.CheckViolation, match='account_password_required'):
        transition(ops, aid, 'NORMAL')                                     # 새 비밀번호 없이 복구 완료 불가
    with pytest.raises(errors.RaiseException, match='WEAK_PASSWORD'):
        ops.execute('SELECT ap.reset_password(%s, %s, 1)', (aid, 'short'))
    assert ops.execute('SELECT ap.reset_password(%s, %s, 1)', (aid, 'new-password-9')).fetchone()[0] == 3
    case_id, *_ = transition(ops, aid, 'NORMAL', reason='본인 확인 완료')
    assert owner.execute('SELECT closed_at IS NOT NULL FROM ap.protection_case WHERE case_id = %s',
                         (case_id,)).fetchone()[0]
    assert login(game, acc)[0] == 'BAD_PASSWORD'
    assert login(game, acc, password='new-password-9')[0] == 'OK'


def test_reset_password_only_while_recovering(ops, make_account):
    acc = make_account()
    with pytest.raises(errors.RaiseException, match='RESET_ONLY_IN_RECOVERING'):
        ops.execute('SELECT ap.reset_password(%s, %s, 1)', (acc['account_id'], 'whatever-123'))


def test_locked_is_terminal(game, ops, owner, make_account):
    acc = make_account()
    case_id, *_ = transition(ops, acc['account_id'], 'LOCKED')
    for target in ('NORMAL', 'SUSPECTED', 'PROTECTED', 'RECOVERING'):
        with pytest.raises(errors.RaiseException, match='TRANSITION_NOT_ALLOWED'):
            transition(ops, acc['account_id'], target)
    assert owner.execute('SELECT closed_at IS NOT NULL FROM ap.protection_case WHERE case_id = %s',
                         (case_id,)).fetchone()[0]
    assert login(game, acc)[0] == 'STATE_BLOCKED'


# ---------------------------------------------------------------- 아이템 이동
def test_transfer_rules(game, ops, owner, make_account):
    a, b = make_account(items=2), make_account(items=0)
    token = login(game, a)[1]
    assert transfer(game, token, a['items'][0], b['account_id'])[1:] == ('APPROVED', None)
    assert transfer(game, token, a['items'][0], b['account_id'])[1:] == ('REJECTED', 'NOT_OWNER')
    with pytest.raises(errors.RaiseException, match='SAME_ACCOUNT'):
        transfer(game, token, a['items'][1], a['account_id'])

    transition(ops, a['account_id'], 'PROTECTED')
    assert transfer(game, token, a['items'][1], b['account_id'])[1:] == ('REJECTED', 'SESSION_REVOKED')
    assert owner.execute('SELECT owner_account_id FROM ap.item WHERE item_id = %s',
                         (a['items'][1],)).fetchone()[0] == a['account_id']
    assert owner.execute("""SELECT count(*) FROM ap.item_transfer it JOIN ap.game_session gs USING (session_id)
                            WHERE gs.account_id = %s AND it.result = 'REJECTED'""",
                         (a['account_id'],)).fetchone()[0] == 2                       # 거절도 기록된다


def test_untradable_item_is_rejected(game, make_account):
    a, b = make_account(items=1, tradable=False), make_account(items=0)
    token = login(game, a)[1]
    assert transfer(game, token, a['items'][0], b['account_id'])[1:] == ('REJECTED', 'NOT_TRADABLE')


# ---------------------------------------------------------------- 권한 (최소 권한)
@pytest.mark.parametrize('stmt', [
    "UPDATE ap.account SET state_code = 'LOCKED'",
    'SELECT email FROM ap.account',
    'SELECT password_hash FROM ap.account',
    'SELECT token_hash FROM ap.game_session',
    "INSERT INTO ap.case_transition VALUES (1, 1, 'NORMAL', 'SUSPECTED', 1, 'x', now())",
    'DELETE FROM ap.login_attempt',
    'SELECT * FROM lab.transfer_item_nolock(%s, 1, 2, 0)',
])
def test_ops_role_cannot_bypass_functions(ops, stmt):
    with pytest.raises(errors.InsufficientPrivilege):
        ops.execute(stmt, ('x',) if '%s' in stmt else None)


@pytest.mark.parametrize('stmt', [
    "SELECT ap.transition_account(1, 'LOCKED', 1, 'x')",
    'SELECT * FROM ap.account',
    'SELECT * FROM ap.v_account_overview',
])
def test_game_role_can_only_login_and_transfer(game, stmt):
    with pytest.raises(errors.InsufficientPrivilege):
        game.execute(stmt)


def test_ops_sees_masked_email(ops, make_account):
    acc = make_account()
    masked = ops.execute('SELECT email_masked FROM ap.v_account_overview WHERE account_id = %s',
                         (acc['account_id'],)).fetchone()[0]
    assert masked == 't***@example.com'


# ---------------------------------------------------------------- 트리거 (소유자 권한으로 직접 바꿔도 막힌다)
def test_owner_cannot_make_disallowed_transition(owner, make_account):
    acc = make_account()
    with pytest.raises(errors.CheckViolation, match='TRANSITION_NOT_ALLOWED'):
        owner.execute("UPDATE ap.account SET state_code = 'RECOVERING' WHERE account_id = %s", (acc['account_id'],))


def test_owner_cannot_change_state_without_recording_it(owner, make_account):
    acc = make_account()
    with pytest.raises(errors.RaiseException, match='STATE_CHANGE_NOT_RECORDED'):
        owner.execute("UPDATE ap.account SET state_code = 'SUSPECTED' WHERE account_id = %s", (acc['account_id'],))
    assert account_row(owner, acc['account_id'])[0] == 'NORMAL'


def test_new_account_must_start_normal(owner):
    with pytest.raises(errors.RaiseException, match='NEW_ACCOUNT_MUST_BE_NORMAL'):
        with owner.transaction():
            owner.execute("""INSERT INTO ap.account (login_id, nickname, email, password_hash, state_code)
                             VALUES ('bad1', 'bad1', 'b@example.com', 'x', 'SUSPECTED')""")


# ---------------------------------------------------------------- 정규화: 하위 타입 burst_signal
def test_burst_detail_only_attaches_to_failed_burst_signal(game, owner, make_account):
    acc = make_account()
    login(game, acc, device_key='new-phone')                     # NEW_DEVICE 신호 1건
    sid = owner.execute("""SELECT rs.signal_id FROM ap.risk_signal rs
                           JOIN ap.login_attempt la ON la.attempt_id = rs.trigger_attempt_id
                           WHERE la.account_id = %s AND rs.rule_code = 'NEW_DEVICE'""",
                        (acc['account_id'],)).fetchone()[0]
    with pytest.raises(errors.ForeignKeyViolation):              # (signal_id, 'FAILED_BURST') 쌍이 없다
        owner.execute('INSERT INTO ap.burst_signal (signal_id, failures_in_window, window_minutes) VALUES (%s, 5, 10)',
                      (sid,))


# ---------------------------------------------------------------- 정규화: 판별 컬럼은 DBMS 가 계산하는 유도 컬럼
@pytest.mark.parametrize('stmt', [
    'UPDATE ap.login_attempt SET success = NOT success',
    "UPDATE ap.item_transfer SET result = 'APPROVED'",
    "UPDATE ap.game_session SET revoke_reason = 'LOGOUT'",
    'UPDATE ap.account_device SET is_trusted = true',
    "UPDATE ap.burst_signal SET rule_code = 'NEW_DEVICE'",
])
def test_derived_columns_cannot_be_written(owner, stmt):
    with pytest.raises(errors.GeneratedAlways):                  # 소유자도 직접 쓸 수 없다 → 갱신 이상 불가
        owner.execute(stmt)


# ---------------------------------------------------------------- 참조 무결성 / 삭제 정책
RESTRICTED = (errors.ForeignKeyViolation, errors.RestrictViolation)    # PG17 은 23503, PG18 부터 23001


def test_account_with_history_cannot_be_deleted(owner, make_account):
    acc = make_account()
    with pytest.raises(RESTRICTED):                               # 계정은 지우지 않고 영구 잠금으로 표시한다
        owner.execute('DELETE FROM ap.account WHERE account_id = %s', (acc['account_id'],))


def test_operator_who_acted_cannot_be_deleted(ops, owner, make_account):
    acc = make_account()
    transition(ops, acc['account_id'], 'SUSPECTED')               # 운영자 1 이 전이 수행
    with pytest.raises(RESTRICTED, match='fk_(case_transition|credential_history)_operator'):   # 부인 방지
        owner.execute('DELETE FROM ap.operator WHERE operator_id = 1')


def test_state_code_cannot_be_renamed(owner):
    with pytest.raises(RESTRICTED):                               # ON UPDATE RESTRICT: 코드값은 불변
        owner.execute("UPDATE ap.protection_state SET state_code = 'OK' WHERE state_code = 'NORMAL'")


def test_deleting_signal_cascades_to_burst_detail(game, owner, make_account):
    acc = make_account()
    for _ in range(5):
        login(game, acc, password='wrong', device_key='attacker-box', ip='203.0.113.7')
    sid = owner.execute("""SELECT rs.signal_id FROM ap.risk_signal rs
                           JOIN ap.login_attempt la ON la.attempt_id = rs.trigger_attempt_id
                           WHERE la.account_id = %s AND rs.rule_code = 'FAILED_BURST'""",
                        (acc['account_id'],)).fetchone()[0]
    assert owner.execute('SELECT count(*) FROM ap.burst_signal WHERE signal_id = %s', (sid,)).fetchone()[0] == 1
    owner.execute('DELETE FROM ap.risk_signal WHERE signal_id = %s', (sid,))          # 하위 타입 행도 함께 삭제
    assert owner.execute('SELECT count(*) FROM ap.burst_signal WHERE signal_id = %s', (sid,)).fetchone()[0] == 0


def test_login_attempt_behind_a_signal_cannot_be_deleted(game, owner, make_account):
    acc = make_account()
    login(game, acc, device_key='new-phone')                      # NEW_DEVICE 신호가 이 시도를 가리킨다
    with pytest.raises(RESTRICTED):
        owner.execute('DELETE FROM ap.login_attempt WHERE account_id = %s', (acc['account_id'],))


def test_burst_rule_must_keep_window_and_threshold(owner):
    with pytest.raises(errors.CheckViolation, match='ck_risk_rule_burst_params'):   # 탐지가 조용히 꺼지는 설정 차단
        owner.execute("UPDATE ap.risk_rule SET window_minutes = NULL WHERE rule_code = 'FAILED_BURST'")


def test_hash_columns_accept_only_sha256_hex(owner):
    with pytest.raises(errors.CheckViolation, match='ck_device_fingerprint_hex'):  # char(64) 는 'abc' 도 공백을 채워 받는다
        owner.execute("INSERT INTO ap.device (fingerprint, platform) VALUES ('abc', 'OTHER')")


def test_last_seen_never_moves_backwards(game, owner, make_account):
    acc = make_account()
    aid = acc['account_id']
    # 나중에 시작한 로그인이 먼저 끝난 상황: 등록기기의 시각이 이 로그인의 now() 보다 뒤
    owner.execute("""UPDATE ap.account_device SET first_seen_at = now() + interval '1 hour',
                                                  last_seen_at  = now() + interval '1 hour' WHERE account_id = %s""", (aid,))
    assert login(game, acc)[0] == 'OK'                            # ck_account_device_seen_order 에 걸리지 않는다
    assert owner.execute("""SELECT last_seen_at >= first_seen_at AND last_seen_at > now() FROM ap.account_device
                            WHERE account_id = %s""", (aid,)).fetchone()[0]
