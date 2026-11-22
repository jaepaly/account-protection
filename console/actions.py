"""변경 요청 — 정책 함수 호출과 거부 사유 해석.

화면은 정책을 다시 구현하지 않는다. 요청을 그대로 DB 함수에 넘기고, DB가 거부하면 그 사유를
운영자가 읽을 수 있는 말로 바꿔 보여줄 뿐이다. 화면 코드가 틀려도 정책은 DB에서 지켜진다.
"""
import logging

from django.db import DatabaseError, transaction

from . import db

log = logging.getLogger('console.security')


class Rejected(Exception):
    """처리 거부. where: 어디서 막았는지(화면 검증 / 정책 함수 / CHECK 제약 / 권한 …)."""

    def __init__(self, code, title, explanation, where, db_message=None, status=409):
        super().__init__(code)
        self.code, self.title, self.explanation = code, title, explanation
        self.where, self.db_message, self.status = where, db_message, status


# DB 오류 메시지의 코드 → (제목, 설명, 막은 곳)
BY_MESSAGE = {
    'TRANSITION_NOT_ALLOWED': ('허용되지 않은 전이',
                               '허용 전이 목록(allowed_transition)에 없는 상태 변경입니다.',
                               '정책 함수 transition_account'),
    'REASON_REQUIRED': ('사유 누락', '모든 전이에는 사유를 남겨야 합니다. 공백만 입력한 것도 거부됩니다.',
                        '정책 함수 transition_account'),
    'OPEN_CASE_MISSING': ('진행 중인 케이스 없음', '이 계정에 진행 중인 보호 케이스가 없습니다.',
                          '정책 함수 transition_account'),
    'RESET_ONLY_IN_RECOVERING': ('비밀번호 재설정 불가', '비밀번호는 「복구 중」 상태에서만 재설정할 수 있습니다.',
                                 '정책 함수 reset_password'),
    'WEAK_PASSWORD': ('비밀번호 길이 부족', '새 비밀번호는 8자 이상이어야 합니다.', '정책 함수 reset_password'),
    'ACCOUNT_NOT_FOUND': ('계정 없음', '요청한 계정이 없습니다.', '정책 함수'),
}
# 위반한 제약 이름 → (코드, 제목, 설명, 막은 곳)
BY_CONSTRAINT = {
    'ck_account_password_required': ('PASSWORD_REQUIRED', '새 비밀번호 미설정',
                                     '로그인할 수 있는 상태로 돌아가려면 먼저 새 비밀번호를 설정해야 합니다. '
                                     '전이 기록과 케이스 종료까지 함께 취소되었습니다.',
                                     'CHECK 제약 ck_account_password_required'),
    'ck_case_transition_reason': ('REASON_REQUIRED', '사유 누락', '모든 전이에는 사유를 남겨야 합니다.',
                                  'CHECK 제약 ck_case_transition_reason'),
    'fk_case_transition_operator': ('OPERATOR_INVALID', '운영자 확인 실패', '전이를 기록할 운영자가 없습니다.',
                                    '외래키 fk_case_transition_operator'),
    'fk_credential_history_operator': ('OPERATOR_INVALID', '운영자 확인 실패', '변경을 기록할 운영자가 없습니다.',
                                       '외래키 fk_credential_history_operator'),
}
# SQLSTATE → (코드, 제목, 설명, 막은 곳)
BY_SQLSTATE = {
    '55P03': ('LOCK_TIMEOUT', '다른 처리가 진행 중',
              '같은 계정의 로그인·아이템 이동·다른 전이가 끝나기를 기다리다 시간이 초과되었습니다. '
              '잠시 뒤 다시 시도하세요.',
              '계정 행 잠금 (lock_timeout)'),
    '57014': ('TIMEOUT', '처리 시간 초과', '처리가 제한 시간 안에 끝나지 않아 취소되었습니다.', 'statement_timeout'),
    '42501': ('PERMISSION_DENIED', '권한 없음', '운영 화면의 DB 역할에 허용되지 않은 작업입니다.', 'DB 권한(GRANT)'),
    '22001': ('TOO_LONG', '입력이 너무 김', '입력 길이가 컬럼 한도를 넘었습니다.', '컬럼 타입'),
}


def interpret(exc):
    """DB 오류 → Rejected. 모르는 오류는 내용을 화면에 내보내지 않고 로그에만 남긴다."""
    cause = exc.__cause__ if exc.__cause__ is not None else exc
    diag = getattr(cause, 'diag', None)
    message = (getattr(diag, 'message_primary', None) or '').strip()
    constraint = getattr(diag, 'constraint_name', None)
    sqlstate = getattr(cause, 'sqlstate', None)

    code = message.split(':', 1)[0].strip()
    if code in BY_MESSAGE:
        title, explanation, where = BY_MESSAGE[code]
        return Rejected(code, title, explanation, where, db_message=message)
    if constraint in BY_CONSTRAINT:
        code, title, explanation, where = BY_CONSTRAINT[constraint]
        return Rejected(code, title, explanation, where, db_message=message)
    if sqlstate in BY_SQLSTATE:
        code, title, explanation, where = BY_SQLSTATE[sqlstate]
        return Rejected(code, title, explanation, where, db_message=message)
    log.error('unexpected database error: sqlstate=%s constraint=%s message=%s', sqlstate, constraint, message)
    return Rejected('DB_ERROR', '처리 실패', '데이터베이스가 요청을 거부했습니다.',
                    f'데이터베이스 (SQLSTATE {sqlstate or "?"})', status=500)


def transition(account_id, to_state, expected_state, operator_id, reason):
    """REQ-07: 상태 전이. 운영자가 화면에서 본 상태(expected_state)와 실제 출발 상태가 다르면 되돌린다.

    두 운영자가 같은 계정을 동시에 열어 둔 경우를 막는다. 예) A가 「의심→정상」으로 종료한 직후
    B의 낡은 화면에서 「보호」를 누르면, 검사 없이는 B가 의도하지 않은 「정상→보호」가 실행된다.
    함수 호출과 비교를 한 트랜잭션에 넣어, 다르면 전이 전체(기록·세션 폐기·자격 회전)를 롤백한다.
    """
    try:
        with transaction.atomic():
            result = db.row('SELECT * FROM ap.transition_account(%s::bigint, %s::text, %s::integer, %s::text)',
                            [account_id, to_state, operator_id, reason])
            if result['from_state'] != expected_state:
                raise Rejected('STALE_SCREEN', '화면이 최신이 아님',
                               f'화면을 연 뒤 다른 처리로 계정 상태가 바뀌었습니다(화면: {expected_state}, '
                               f'실제: {result["from_state"]}). 요청한 전이는 실행하지 않고 되돌렸습니다. '
                               '계정을 다시 열어 현재 상태를 확인하세요.',
                               '화면 검증 (전이와 같은 트랜잭션에서 롤백)')
        return result
    except DatabaseError as exc:
        raise interpret(exc) from exc


def reset_password(account_id, new_password, operator_id):
    """REQ-10: 「복구 중」 계정의 새 비밀번호 설정. 비밀번호는 로그·메시지 어디에도 남기지 않는다."""
    try:
        with transaction.atomic():
            return db.scalar('SELECT ap.reset_password(%s::bigint, %s::text, %s::integer)',
                             [account_id, new_password, operator_id])
    except DatabaseError as exc:
        raise interpret(exc) from exc


def detect_all():
    """REQ-15: 전체 로그인 이력에 대해 탐지 실행. 이미 만든 신호는 UNIQUE 제약으로 중복되지 않는다."""
    try:
        with transaction.atomic():
            return db.scalar('SELECT ap.detect_risks()')
    except DatabaseError as exc:
        raise interpret(exc) from exc
