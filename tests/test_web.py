"""운영 콘솔(Django) 검증: 접근 통제(NFR-14), 운영자 신원 기록(REQ-13), 전이·복구(REQ-07, 10), 예외 화면(REQ-16)."""
import os
import secrets

os.environ['AP_DB_TARGET'] = 'test'                      # web.settings 가 테스트 DB에 붙게 한다
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'web.settings')

import pytest  # noqa: E402

from conftest import TEST_DB, login  # noqa: E402

PROTECTED_URLS = ['/', '/accounts/', '/accounts/1/', '/cases/', '/cases/1/', '/stats/']


@pytest.fixture(scope='session')
def web(fresh_test_db):
    """Django 를 테스트 DB에 붙이고 웹 로그인 계정을 만든다. 반환값: 그 계정들의 (임의) 비밀번호."""
    import django
    django.setup()
    from django.conf import settings
    assert settings.DATABASES['default']['NAME'] == TEST_DB, '개발 DB에 테스트를 돌리지 않는다'
    from django.contrib.auth import get_user_model
    from django.core.management import call_command
    from django.test.utils import setup_test_environment
    setup_test_environment()
    call_command('migrate', verbosity=0)
    password = secrets.token_urlsafe(16)
    for name in ('op_kim', 'op_lee', 'stranger'):        # stranger: 웹 계정은 있지만 ap.operator 에는 없다
        get_user_model().objects.create_user(name, password=password)
    return password


def sign_in(password, username='op_kim', **client_options):
    from django.test import Client
    client = Client(**client_options)
    response = client.post('/login/', {'username': username, 'password': password})
    assert response.status_code == 302, '로그인 실패'
    return client


@pytest.fixture
def console(web):
    return sign_in(web)


def state(owner, account_id):
    return owner.execute('SELECT state_code FROM ap.account WHERE account_id = %s', (account_id,)).fetchone()[0]


def transitions(owner, account_id):
    return owner.execute("""SELECT ct.from_state, ct.to_state, ct.operator_id FROM ap.case_transition ct
                            JOIN ap.protection_case pc ON pc.case_id = ct.case_id
                            WHERE pc.account_id = %s ORDER BY ct.case_id, ct.seq""", (account_id,)).fetchall()


def post_transition(client, account_id, to_state, expected, reason='테스트 사유', **extra):
    return client.post(f'/accounts/{account_id}/transition/',
                       {'to_state': to_state, 'expected_state': expected, 'reason': reason, **extra})


def body(response):
    return response.content.decode('utf-8')


# ---------------------------------------------------------------- 접근 통제 (NFR-14)
def test_web_connects_as_least_privilege_role(web):
    from django.db import DatabaseError, connection
    with connection.cursor() as cur:
        cur.execute('SELECT current_user')
        assert cur.fetchone()[0] == 'ap_ops'
    with pytest.raises(DatabaseError), connection.cursor() as cur:
        cur.execute("UPDATE ap.account SET state_code = 'LOCKED'")       # 화면 코드가 직접 바꾸는 길은 없다


@pytest.mark.parametrize('url', PROTECTED_URLS)
def test_anonymous_request_is_sent_to_login(web, url):
    from django.test import Client
    response = Client().get(url)
    assert response.status_code == 302 and response['Location'].startswith('/login/?next=')


def test_anonymous_post_changes_nothing(web, owner, make_account):
    from django.test import Client
    acc = make_account()
    response = post_transition(Client(), acc['account_id'], 'PROTECTED', 'NORMAL')
    assert response.status_code == 302 and response['Location'].startswith('/login/')
    assert state(owner, acc['account_id']) == 'NORMAL' and transitions(owner, acc['account_id']) == []


def test_wrong_password_and_non_operator_get_the_same_refusal(web):
    from django.test import Client
    wrong = Client().post('/login/', {'username': 'op_kim', 'password': web + 'x'})
    stranger_client = Client()
    stranger = stranger_client.post('/login/', {'username': 'stranger', 'password': web})   # 비밀번호는 맞다
    missing = Client().post('/login/', {'username': 'nobody', 'password': web})
    message = '아이디 또는 비밀번호가 올바르지 않습니다.'
    for response in (wrong, stranger, missing):
        assert response.status_code == 200 and message in body(response)
    assert stranger_client.get('/').status_code == 302                    # 로그인되지 않았다


def test_deactivated_operator_is_cut_off_on_the_next_request(web, owner):
    client = sign_in(web, 'op_lee')
    assert client.get('/').status_code == 200
    owner.execute("UPDATE ap.operator SET is_active = false WHERE username = 'op_lee'")
    try:
        assert client.get('/').status_code == 403                         # 세션이 살아 있어도 바로 차단
        assert client.get('/').status_code == 302                         # 그리고 로그아웃되어 있다
    finally:
        owner.execute("UPDATE ap.operator SET is_active = true WHERE username = 'op_lee'")


def test_state_changes_only_by_post_with_csrf_token(web, owner, make_account):
    from django.test import Client
    acc = make_account()
    client = Client(enforce_csrf_checks=True)
    client.get('/login/')
    token = client.cookies['csrftoken'].value
    assert client.post('/login/', {'username': 'op_kim', 'password': web,
                                   'csrfmiddlewaretoken': token}).status_code == 302
    assert client.get(f'/accounts/{acc["account_id"]}/transition/').status_code == 405
    forged = post_transition(client, acc['account_id'], 'PROTECTED', 'NORMAL')      # 토큰 없는 요청
    assert forged.status_code == 403 and '데이터는 바뀌지 않았습니다' in body(forged)
    assert state(owner, acc['account_id']) == 'NORMAL'


def test_logout_is_post_only(web):
    client = sign_in(web)
    assert client.get('/logout/').status_code == 405
    assert client.post('/logout/').status_code == 302
    assert client.get('/').status_code == 302


def test_responses_carry_security_headers(console):
    response = console.get('/')
    assert "default-src 'none'" in response['Content-Security-Policy']
    assert response['X-Frame-Options'] == 'DENY' and response['Cache-Control'] == 'no-store'


# ---------------------------------------------------------------- 조회 화면 (REQ-05, 06, 12, 14)
def test_queue_lists_open_signal_and_account_page_masks_email(console, game, make_account):
    acc = make_account()
    for _ in range(5):
        login(game, acc, password='wrong-password')
    assert acc['login_id'] in body(console.get('/?rule=FAILED_BURST'))
    page = body(console.get(f'/accounts/{acc["account_id"]}/'))
    assert 't***@example.com' in page and f'{acc["login_id"]}@example.com' not in page
    assert '10분 안에 실패 5회' in page and 'BAD_PASSWORD' in page       # 미처리 신호 + 타임라인


def test_every_page_renders(console, make_account):
    acc = make_account()
    post_transition(console, acc['account_id'], 'PROTECTED', 'NORMAL')
    case_id = console.get(f'/accounts/{acc["account_id"]}/').context['acc']['open_case_id']
    urls = ['/', '/accounts/', f'/accounts/?q={acc["login_id"]}&state=PROTECTED&attention=1', '/cases/',
            '/cases/?status=all', f'/cases/{case_id}/', '/stats/', '/stats/?period=all']
    urls += [f'/accounts/{acc["account_id"]}/?tab={tab}' for tab in ('timeline', 'sessions', 'devices', 'items', 'cases')]
    for url in urls:
        assert console.get(url).status_code == 200, url
    for url in ('/accounts/999999999/', '/cases/999999999/', '/accounts/99999999999999999999/', '/nothing/'):
        assert console.get(url).status_code == 404, url


def test_search_treats_like_wildcards_literally(console, make_account):
    make_account()
    assert console.get('/accounts/?q=%25').context['page'].total == 0     # '%' 한 글자: 전체가 아니라 0건
    assert console.get('/accounts/?q=tester').context['page'].total > 0


# ---------------------------------------------------------------- 전이 (REQ-07, 13)
def test_transition_is_recorded_under_the_signed_in_operator(web, owner, make_account):
    acc = make_account()
    kim, lee = (owner.execute('SELECT operator_id FROM ap.operator WHERE username = %s', (name,)).fetchone()[0]
                for name in ('op_kim', 'op_lee'))
    response = post_transition(sign_in(web, 'op_lee'), acc['account_id'], 'SUSPECTED', 'NORMAL',
                               operator_id=kim, p_operator_id=kim)        # 남의 이름을 끼워 넣어도 무시된다
    assert response.status_code == 302 and '?done=' in response['Location']
    assert transitions(owner, acc['account_id']) == [('NORMAL', 'SUSPECTED', lee)]


def test_result_banner_is_read_back_from_the_database(console, game, make_account):
    acc = make_account(items=4)
    assert login(game, acc)[0] == 'OK'
    response = post_transition(console, acc['account_id'], 'PROTECTED', 'NORMAL')
    result = console.get(response['Location']).context['result']
    assert (result['revoked_sessions'], result['snapshot_items'], result['operator_name']) == (1, 4, '김운영')


def test_stale_screen_is_rolled_back_completely(console, owner, game, make_account):
    """화면은 「의심」으로 알고 「보호」를 눌렀지만 실제로는 「정상」 — 정상→보호 가 실행되면 안 된다."""
    acc = make_account()
    response = post_transition(console, acc['account_id'], 'PROTECTED', 'SUSPECTED')
    assert response.status_code == 409 and 'STALE_SCREEN' in body(response)
    assert response.context['unchanged'] is True
    assert state(owner, acc['account_id']) == 'NORMAL' and transitions(owner, acc['account_id']) == []
    assert login(game, acc)[0] == 'OK'                                    # 비밀번호 폐기도 되돌려졌다


@pytest.mark.parametrize('to_state, reason, code', [
    ('RECOVERING', '바로 복구로', 'TRANSITION_NOT_ALLOWED'),
    ('NORMAL', '제자리', 'TRANSITION_NOT_ALLOWED'),
    ('NO_SUCH_STATE', '없는 상태', 'TRANSITION_NOT_ALLOWED'),
    ('SUSPECTED', '   ', 'REASON_REQUIRED'),
    ('SUSPECTED', '', 'REASON_REQUIRED'),
])
def test_rejected_transition_shows_reason_and_unchanged_data(console, owner, make_account, to_state, reason, code):
    acc = make_account()
    response = post_transition(console, acc['account_id'], to_state, 'NORMAL', reason=reason)
    assert response.status_code == 409
    assert code in body(response) and '변경 없음' in body(response)
    assert response.context['unchanged'] is True
    assert state(owner, acc['account_id']) == 'NORMAL' and transitions(owner, acc['account_id']) == []


def test_malformed_request_is_rejected(console, owner, make_account):
    acc = make_account()
    response = post_transition(console, acc['account_id'], 'SUSPECTED', 'NORMAL', reason='가' * 501)
    assert response.status_code == 400 and 'INVALID_REQUEST' in body(response)
    assert state(owner, acc['account_id']) == 'NORMAL'


def test_terminal_transition_needs_explicit_confirmation(console, owner, make_account):
    acc = make_account()
    response = post_transition(console, acc['account_id'], 'LOCKED', 'NORMAL')
    assert response.status_code == 400 and 'CONFIRM_REQUIRED' in body(response)
    assert state(owner, acc['account_id']) == 'NORMAL'
    assert post_transition(console, acc['account_id'], 'LOCKED', 'NORMAL', confirm_terminal='on').status_code == 302
    assert state(owner, acc['account_id']) == 'LOCKED'
    page = console.get(f'/accounts/{acc["account_id"]}/')
    assert page.context['transitions'] == [] and '종착 상태' in body(page)


# ---------------------------------------------------------------- 복구 (REQ-10, NFR-03)
def test_recovery_needs_new_password_and_then_completes(console, owner, game, make_account):
    acc, new_password = make_account(), 'new-passphrase-2026'
    account_id = acc['account_id']
    assert post_transition(console, account_id, 'PROTECTED', 'NORMAL').status_code == 302
    assert post_transition(console, account_id, 'RECOVERING', 'PROTECTED').status_code == 302

    blocked = post_transition(console, account_id, 'NORMAL', 'RECOVERING')            # 새 비밀번호 없이 복구 완료
    assert blocked.status_code == 409 and 'PASSWORD_REQUIRED' in body(blocked)
    assert blocked.context['unchanged'] is True
    assert state(owner, account_id) == 'RECOVERING' and len(transitions(owner, account_id)) == 2
    assert owner.execute('SELECT closed_at FROM ap.protection_case WHERE account_id = %s',
                         (account_id,)).fetchone()[0] is None                         # 케이스 종료도 취소됐다

    url = f'/accounts/{account_id}/password/'
    mismatch = console.post(url, {'new_password': new_password, 'confirm_password': new_password + '!'})
    short = console.post(url, {'new_password': 'short12', 'confirm_password': 'short12'})
    assert (mismatch.status_code, short.status_code) == (400, 409)
    assert 'PASSWORD_MISMATCH' in body(mismatch) and 'WEAK_PASSWORD' in body(short)
    assert new_password not in body(mismatch) and 'short12' not in body(short)        # 입력값을 되돌려 보이지 않는다
    assert console.post(url, {'new_password': new_password, 'confirm_password': new_password}).status_code == 302

    assert post_transition(console, account_id, 'NORMAL', 'RECOVERING').status_code == 302
    assert state(owner, account_id) == 'NORMAL'
    assert login(game, acc)[0] == 'BAD_PASSWORD' and login(game, acc, password=new_password)[0] == 'OK'


def test_password_reset_outside_recovering_is_rejected(console, game, make_account):
    acc = make_account()
    response = console.post(f'/accounts/{acc["account_id"]}/password/',
                            {'new_password': 'another-pass-123', 'confirm_password': 'another-pass-123'})
    assert response.status_code == 409 and 'RESET_ONLY_IN_RECOVERING' in body(response)
    assert login(game, acc)[0] == 'OK'                                                # 기존 비밀번호 그대로


# ---------------------------------------------------------------- 탐지 (REQ-15)
def test_bulk_detection_reports_only_new_signals(console, owner, make_account):
    acc = make_account()
    device = owner.execute('SELECT device_id FROM ap.account_device WHERE account_id = %s',
                           (acc['account_id'],)).fetchone()[0]
    owner.execute("""INSERT INTO ap.login_attempt (account_id, device_id, ip_address, attempted_at, failure_reason)
                     SELECT %s, %s, '10.9.9.9', now() - interval '3 days' + n * interval '10 seconds', 'BAD_PASSWORD'
                       FROM generate_series(1, 5) n""", (acc['account_id'], device))   # 함수를 거치지 않은 과거 이력
    burst = "SELECT count(*) FROM ap.v_risk_queue WHERE account_id = %s AND rule_code = 'FAILED_BURST'"
    assert owner.execute(burst, (acc['account_id'],)).fetchone()[0] == 0
    first = console.post('/detect/', follow=True)
    assert '새로 만든 위험 신호' in body(first) and '새로 만든 위험 신호 0건' not in body(first)
    assert owner.execute(burst, (acc['account_id'],)).fetchone()[0] == 1
    second = console.post('/detect/', follow=True)                                     # 다시 실행해도 중복이 생기지 않는다
    assert '새로 만든 위험 신호 0건' in body(second)
    assert owner.execute(burst, (acc['account_id'],)).fetchone()[0] == 1
