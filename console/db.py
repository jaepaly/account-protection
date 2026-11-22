"""업무 스키마(ap)용 얇은 SQL 계층.

ORM 모델을 두지 않는다. 웹 역할(ap_ops)은 ap 스키마에 쓰기 권한이 없고, 변경은 정책 함수
(transition_account, reset_password, detect_risks)로만 일어나므로 SQL을 그대로 쓰는 편이 정직하다.
값은 항상 매개변수(%s)로 넘긴다 — SQL 문자열에 입력을 이어 붙이지 않는다.
"""
from django.db import connection


def rows(sql, params=None):
    with connection.cursor() as cur:
        cur.execute(sql, params)
        names = [col[0] for col in cur.description]
        return [dict(zip(names, record)) for record in cur.fetchall()]


def row(sql, params=None):
    result = rows(sql, params)
    return result[0] if result else None


def scalar(sql, params=None):
    with connection.cursor() as cur:
        cur.execute(sql, params)
        record = cur.fetchone()
        return record[0] if record else None
