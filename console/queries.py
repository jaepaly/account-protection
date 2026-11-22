"""운영 콘솔의 조회 SQL (ap_ops 권한: ap 스키마 조회 전용, 민감 컬럼 제외)."""
from . import db

PAGE_SIZE = 25

# 타임라인 필터: 화면 선택지 → v_audit_timeline.event_type
TIMELINE_FILTERS = {
    'key':        ('주요 사건', ['LOGIN_FAILED', 'RISK_SIGNAL', 'STATE_TRANSITION', 'SESSION_REVOKED', 'TRANSFER_REJECTED']),
    'login':      ('로그인', ['LOGIN_SUCCESS', 'LOGIN_FAILED']),
    'signal':     ('위험 신호', ['RISK_SIGNAL']),
    'transition': ('상태 전이', ['STATE_TRANSITION']),
    'session':    ('세션 폐기', ['SESSION_REVOKED']),
    'transfer':   ('아이템 이동', ['TRANSFER_APPROVED', 'TRANSFER_REJECTED']),
}


class Page:
    def __init__(self, number, total, size=PAGE_SIZE):
        self.total, self.size = total, size
        self.pages = max(1, -(-total // size))
        self.number = min(max(1, number), self.pages)
        self.offset = (self.number - 1) * size
        self.has_prev, self.has_next = self.number > 1, self.number < self.pages
        self.prev, self.next = self.number - 1, self.number + 1
        self.first_row = self.offset + 1 if total else 0
        self.last_row = min(self.offset + size, total)


def like_pattern(text):
    """ILIKE 패턴용 이스케이프 — 입력의 %, _ 를 와일드카드가 아니라 글자 그대로 찾는다."""
    for ch in ('\\', '%', '_'):
        text = text.replace(ch, '\\' + ch)
    return '%' + text + '%'


# ------------------------------------------------------------------ 위험 신호 큐 (REQ-05)
def state_counts():
    return db.rows("""
        SELECT ps.state_code, ps.label_ko, count(a.account_id) AS n
          FROM ap.protection_state ps
          LEFT JOIN ap.account a ON a.state_code = ps.state_code
         GROUP BY ps.state_code, ps.label_ko, ps.sort_order
         ORDER BY ps.sort_order""")


def risk_rules():
    return db.rows("""
        SELECT rr.rule_code, rr.name_ko, rr.severity, rr.is_enabled, rr.window_minutes, rr.threshold,
               (SELECT count(*) FROM ap.risk_signal rs WHERE rs.rule_code = rr.rule_code AND rs.case_id IS NULL) AS open
          FROM ap.risk_rule rr ORDER BY rr.severity DESC, rr.rule_code""")


def risk_queue(rule, page_number):
    where, params = 'q.case_id IS NULL', []
    if rule:
        where += ' AND q.rule_code = %s'
        params.append(rule)
    page = Page(page_number, db.scalar(f'SELECT count(*) FROM ap.v_risk_queue q WHERE {where}', params))
    signals = db.rows(f"""
        SELECT q.signal_id, q.account_id, q.login_id, q.state_code, ps.label_ko AS state_label,
               q.rule_code, q.rule_name, q.severity, q.occurred_at, q.detected_at,
               host(q.ip_address) AS ip, q.device_id, q.failures_in_window, q.window_minutes
          FROM ap.v_risk_queue q
          JOIN ap.protection_state ps ON ps.state_code = q.state_code
         WHERE {where}
         ORDER BY q.severity DESC, q.occurred_at DESC, q.signal_id DESC
         LIMIT %s OFFSET %s""", params + [page.size, page.offset])
    return signals, page


# ------------------------------------------------------------------ 계정 목록·상세 (REQ-06)
def accounts(search, state, attention, page_number):
    where, params = ['true'], []
    if search:
        clause = '(v.login_id ILIKE %s OR v.nickname ILIKE %s'
        params += [like_pattern(search)] * 2
        if search.isdigit() and len(search) < 18:
            clause += ' OR v.account_id = %s'
            params.append(int(search))
        where.append(clause + ')')
    if state:
        where.append('v.state_code = %s')
        params.append(state)
    if attention:
        where.append('v.open_signals > 0')
    where = ' AND '.join(where)
    page = Page(page_number, db.scalar(f'SELECT count(*) FROM ap.v_account_overview v WHERE {where}', params))
    found = db.rows(f"""
        SELECT v.account_id, v.login_id, v.nickname, v.email_masked, v.state_code, v.state_label,
               v.active_sessions, v.open_signals, v.item_count, v.open_case_id
          FROM ap.v_account_overview v
         WHERE {where}
         ORDER BY v.account_id
         LIMIT %s OFFSET %s""", params + [page.size, page.offset])
    return found, page


def account(account_id):
    """계정 개요. 이메일은 마스킹 뷰로만 읽는다(원문 컬럼에는 권한이 없다).

    password_set: 비밀번호 해시는 읽을 수 없으므로 현재 자격증명 버전의 이력 사유로 판단한다.
    FORCED_ROTATION 이면 보호 조치로 비밀번호가 폐기된 상태다.
    """
    return db.row("""
        SELECT v.*, ch.reason AS credential_reason, ch.changed_at AS credential_changed_at,
               (ch.reason <> 'FORCED_ROTATION') AS password_set,
               ps.allows_login, ps.allows_transfer
          FROM ap.v_account_overview v
          JOIN ap.protection_state ps ON ps.state_code = v.state_code
          JOIN ap.credential_history ch ON ch.account_id = v.account_id AND ch.version = v.credential_version
         WHERE v.account_id = %s""", [account_id])


def allowed_transitions(state_code):
    """현재 상태에서 허용된 전이와 동반 조치 — 전부 allowed_transition 데이터에서 온다(NFR-11).

    is_terminal: 도착 상태에서 나가는 전이가 없다 = 되돌릴 수 없다(BR-07).
    """
    return db.rows("""
        SELECT t.to_state, ps.label_ko AS to_label, t.description,
               t.revoke_sessions, t.rotate_credential, t.snapshot_assets, ps.closes_case,
               NOT EXISTS (SELECT 1 FROM ap.allowed_transition n WHERE n.from_state = t.to_state) AS is_terminal
          FROM ap.allowed_transition t
          JOIN ap.protection_state ps ON ps.state_code = t.to_state
         WHERE t.from_state = %s
         ORDER BY ps.sort_order""", [state_code])


def evidence(account_id):
    """처리 전후를 비교할 값 — 거부된 요청이 아무것도 바꾸지 않았음을 보여주는 근거(REQ-16)."""
    return db.row("""
        SELECT a.state_code, ps.label_ko AS state_label, a.credential_version,
               (SELECT count(*) FROM ap.case_transition ct JOIN ap.protection_case pc ON pc.case_id = ct.case_id
                 WHERE pc.account_id = a.account_id) AS transitions,
               (SELECT max(ct.transitioned_at) FROM ap.case_transition ct
                  JOIN ap.protection_case pc ON pc.case_id = ct.case_id
                 WHERE pc.account_id = a.account_id) AS last_transition_at,
               (SELECT count(*) FROM ap.protection_case pc
                 WHERE pc.account_id = a.account_id AND pc.closed_at IS NULL) AS open_cases,
               (SELECT count(*) FROM ap.credential_history ch WHERE ch.account_id = a.account_id) AS credential_rows,
               (SELECT count(*) FROM ap.game_session gs
                 WHERE gs.account_id = a.account_id AND gs.revoked_at IS NULL AND gs.expires_at > now()
                   AND gs.issued_credential_version = a.credential_version) AS active_sessions
          FROM ap.account a
          JOIN ap.protection_state ps ON ps.state_code = a.state_code
         WHERE a.account_id = %s""", [account_id])


def transition_result(account_id, case_id, seq):
    """방금 실행한 전이를 DB에서 다시 읽는다 — 화면의 결과는 함수 반환값이 아니라 저장된 기록이다."""
    return db.row("""
        SELECT ct.case_id, ct.seq, fs.label_ko AS from_label, ct.to_state, ts.label_ko AS to_label,
               ct.reason, ct.transitioned_at, coalesce(o.display_name, '시스템') AS operator_name,
               t.revoke_sessions, t.rotate_credential, t.snapshot_assets, pc.closed_at,
               (SELECT count(*) FROM ap.game_session gs
                 WHERE gs.revoked_case_id = ct.case_id AND gs.revoked_seq = ct.seq) AS revoked_sessions,
               (SELECT count(*) FROM ap.case_asset_snapshot s WHERE s.case_id = ct.case_id) AS snapshot_items,
               (SELECT count(*) FROM ap.risk_signal rs WHERE rs.case_id = ct.case_id) AS linked_signals
          FROM ap.case_transition ct
          JOIN ap.protection_case pc ON pc.case_id = ct.case_id
          JOIN ap.allowed_transition t ON t.from_state = ct.from_state AND t.to_state = ct.to_state
          JOIN ap.protection_state fs ON fs.state_code = ct.from_state
          JOIN ap.protection_state ts ON ts.state_code = ct.to_state
          LEFT JOIN ap.operator o ON o.operator_id = ct.operator_id
         WHERE pc.account_id = %s AND ct.case_id = %s AND ct.seq = %s""", [account_id, case_id, seq])


def account_signals(account_id):
    return db.rows("""
        SELECT q.signal_id, q.rule_name, q.severity, q.occurred_at, host(q.ip_address) AS ip, q.device_id,
               q.failures_in_window, q.window_minutes
          FROM ap.v_risk_queue q
         WHERE q.account_id = %s AND q.case_id IS NULL
         ORDER BY q.occurred_at DESC""", [account_id])


def timeline(account_id, event_filter, page_number):
    """REQ-12: 로그인·위험 신호·상태 전이·세션 폐기·아이템 이동을 한 줄로 합친 뷰를 계정으로 걸러 읽는다."""
    where, params = 't.account_id = %s', [account_id]
    if event_filter in TIMELINE_FILTERS:
        where += ' AND t.event_type = ANY(%s)'
        params.append(TIMELINE_FILTERS[event_filter][1])
    page = Page(page_number, db.scalar(f'SELECT count(*) FROM ap.v_audit_timeline t WHERE {where}', params), size=40)
    events = db.rows(f"""
        SELECT t.occurred_at, t.event_type, t.detail, t.case_id, t.ref_id
          FROM ap.v_audit_timeline t
         WHERE {where}
         ORDER BY t.occurred_at DESC, t.event_type, t.ref_id DESC
         LIMIT %s OFFSET %s""", params + [page.size, page.offset])
    return events, page


def sessions(account_id):
    summary = db.rows("""
        SELECT s.status, count(*) AS n FROM ap.v_session_status s WHERE s.account_id = %s GROUP BY s.status""",
                      [account_id])
    recent = db.rows("""
        SELECT s.session_id, s.device_id, d.platform, host(s.ip_address) AS ip, s.issued_at, s.expires_at,
               s.revoked_at, s.revoke_reason, s.status, gs.revoked_case_id, gs.revoked_seq
          FROM ap.v_session_status s
          JOIN ap.game_session gs ON gs.session_id = s.session_id
          JOIN ap.device d ON d.device_id = s.device_id
         WHERE s.account_id = %s
         ORDER BY s.issued_at DESC
         LIMIT 30""", [account_id])
    return {r['status']: r['n'] for r in summary}, recent


def devices(account_id):
    """other_accounts: 같은 기기로 로그인에 성공한 다른 계정 수 — 탈취 조사의 단서."""
    return db.rows("""
        SELECT ad.device_id, d.platform, ad.first_seen_at, ad.last_seen_at, ad.is_trusted, ad.trusted_at,
               (SELECT count(*) FROM ap.account_device x
                 WHERE x.device_id = ad.device_id AND x.account_id <> ad.account_id) AS other_accounts,
               (SELECT count(*) FROM ap.login_attempt la
                 WHERE la.account_id = ad.account_id AND la.device_id = ad.device_id AND NOT la.success) AS failures
          FROM ap.account_device ad
          JOIN ap.device d ON d.device_id = ad.device_id
         WHERE ad.account_id = %s
         ORDER BY ad.last_seen_at DESC""", [account_id])


RARITY_ORDER = "array_position(ARRAY['COMMON', 'RARE', 'EPIC', 'LEGENDARY']::varchar[], it.rarity)"


def items(account_id):
    return db.rows(f"""
        SELECT i.item_id, it.name, it.rarity, it.is_tradable, i.acquired_at
          FROM ap.item i
          JOIN ap.item_template it ON it.template_id = i.template_id
         WHERE i.owner_account_id = %s
         ORDER BY {RARITY_ORDER} DESC, i.item_id
         LIMIT 200""", [account_id])


# ------------------------------------------------------------------ 보호 케이스
CASE_SELECT = """
        SELECT pc.case_id, pc.account_id, a.login_id, pc.opened_at, pc.closed_at,
               last.to_state AS case_state, last.label_ko AS case_state_label,
               (SELECT count(*) FROM ap.case_transition ct WHERE ct.case_id = pc.case_id) AS transitions,
               (SELECT count(*) FROM ap.risk_signal rs WHERE rs.case_id = pc.case_id) AS signals,
               (SELECT count(*) FROM ap.case_asset_snapshot s WHERE s.case_id = pc.case_id) AS snapshot_items
          FROM ap.protection_case pc
          JOIN ap.account a ON a.account_id = pc.account_id
          LEFT JOIN LATERAL (SELECT ct.to_state, s.label_ko
                               FROM ap.case_transition ct
                               JOIN ap.protection_state s ON s.state_code = ct.to_state
                              WHERE ct.case_id = pc.case_id
                              ORDER BY ct.seq DESC LIMIT 1) last ON true"""


def cases(status, account_id, page_number):
    where, params = ['true'], []
    if status == 'open':
        where.append('pc.closed_at IS NULL')
    elif status == 'closed':
        where.append('pc.closed_at IS NOT NULL')
    if account_id:
        where.append('pc.account_id = %s')
        params.append(account_id)
    where = ' AND '.join(where)
    page = Page(page_number, db.scalar(f'SELECT count(*) FROM ap.protection_case pc WHERE {where}', params))
    found = db.rows(f"""{CASE_SELECT}
         WHERE {where}
         ORDER BY (pc.closed_at IS NULL) DESC, pc.opened_at DESC
         LIMIT %s OFFSET %s""", params + [page.size, page.offset])
    return found, page


def case(case_id):
    return db.row(f'{CASE_SELECT} WHERE pc.case_id = %s', [case_id])


def case_transitions(case_id):
    """전이 기록 + 그 전이가 실제로 폐기한 세션 수 — 폐기된 세션에서 원인 전이를 역추적할 수 있다(NFR-09)."""
    return db.rows("""
        SELECT ct.seq, ct.from_state, fs.label_ko AS from_label, ct.to_state, ts.label_ko AS to_label,
               ct.reason, ct.transitioned_at, coalesce(o.display_name, '시스템') AS operator_name,
               t.revoke_sessions, t.rotate_credential, t.snapshot_assets,
               (SELECT count(*) FROM ap.game_session gs
                 WHERE gs.revoked_case_id = ct.case_id AND gs.revoked_seq = ct.seq) AS revoked_sessions
          FROM ap.case_transition ct
          JOIN ap.allowed_transition t ON t.from_state = ct.from_state AND t.to_state = ct.to_state
          JOIN ap.protection_state fs ON fs.state_code = ct.from_state
          JOIN ap.protection_state ts ON ts.state_code = ct.to_state
          LEFT JOIN ap.operator o ON o.operator_id = ct.operator_id
         WHERE ct.case_id = %s
         ORDER BY ct.seq""", [case_id])


def case_signals(case_id):
    return db.rows("""
        SELECT q.signal_id, q.rule_name, q.severity, q.occurred_at, host(q.ip_address) AS ip, q.device_id,
               q.failures_in_window, q.window_minutes
          FROM ap.v_risk_queue q WHERE q.case_id = %s ORDER BY q.occurred_at""", [case_id])


def case_snapshot(case_id):
    """동결 목록과 현재 소유자 비교 — 보호 진입 뒤에도 그대로 있는지 확인하는 복구 기준선."""
    return db.rows(f"""
        SELECT s.item_id, it.name, it.rarity, it.is_tradable, s.captured_at,
               i.owner_account_id, oa.login_id AS owner_login,
               (i.owner_account_id = pc.account_id) AS still_owned
          FROM ap.case_asset_snapshot s
          JOIN ap.protection_case pc ON pc.case_id = s.case_id
          JOIN ap.item i ON i.item_id = s.item_id
          JOIN ap.item_template it ON it.template_id = i.template_id
          JOIN ap.account oa ON oa.account_id = i.owner_account_id
         WHERE s.case_id = %s
         ORDER BY {RARITY_ORDER} DESC, s.item_id""", [case_id])


# ------------------------------------------------------------------ 통계 (REQ-14)
def stats_signals(days):
    """규칙별 신호 수. ROLLUP 으로 합계 행을 함께 얻는다(is_total = 1)."""
    return db.rows("""
        SELECT rr.rule_code, max(rr.name_ko) AS name_ko, max(rr.severity) AS severity,
               count(rs.signal_id) AS total,
               count(rs.signal_id) FILTER (WHERE rs.case_id IS NULL) AS open,
               count(rs.signal_id) FILTER (WHERE rs.case_id IS NOT NULL) AS handled,
               GROUPING(rr.rule_code) AS is_total
          FROM ap.risk_rule rr
          LEFT JOIN ap.risk_signal rs ON rs.rule_code = rr.rule_code
               AND (%s::int IS NULL OR rs.detected_at >= now() - make_interval(days => %s::int))
         GROUP BY ROLLUP (rr.rule_code)
         ORDER BY GROUPING(rr.rule_code), max(rr.severity) DESC, rr.rule_code""", [days, days])


def stats_transitions(days):
    """전이별 처리 건수 — 허용 전이 전체를 기준으로 하므로 한 번도 쓰이지 않은 전이도 0건으로 나온다."""
    return db.rows("""
        SELECT t.from_state, fs.label_ko AS from_label, t.to_state, ts.label_ko AS to_label,
               count(ct.seq) AS n, max(ct.transitioned_at) AS last_at
          FROM ap.allowed_transition t
          JOIN ap.protection_state fs ON fs.state_code = t.from_state
          JOIN ap.protection_state ts ON ts.state_code = t.to_state
          LEFT JOIN ap.case_transition ct ON ct.from_state = t.from_state AND ct.to_state = t.to_state
               AND (%s::int IS NULL OR ct.transitioned_at >= now() - make_interval(days => %s::int))
         GROUP BY t.from_state, fs.label_ko, fs.sort_order, t.to_state, ts.label_ko, ts.sort_order
         ORDER BY fs.sort_order, ts.sort_order""", [days, days])


def stats_operators(days):
    return db.rows("""
        SELECT coalesce(o.display_name, '시스템') AS name, count(*) AS n, max(ct.transitioned_at) AS last_at
          FROM ap.case_transition ct
          LEFT JOIN ap.operator o ON o.operator_id = ct.operator_id
         WHERE %s::int IS NULL OR ct.transitioned_at >= now() - make_interval(days => %s::int)
         GROUP BY coalesce(o.display_name, '시스템')
         ORDER BY n DESC, name""", [days, days])


def stats_cases():
    return db.row("""
        SELECT count(*) FILTER (WHERE closed_at IS NULL) AS open,
               count(*) FILTER (WHERE closed_at IS NOT NULL) AS closed,
               avg(closed_at - opened_at) FILTER (WHERE closed_at IS NOT NULL) AS avg_duration
          FROM ap.protection_case""")
