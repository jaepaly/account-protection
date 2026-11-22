"""웹 로그인 계정(Django auth_user)과 운영자(ap.operator)의 매핑 — 사용자명이 같으면 같은 사람이다."""
from . import db


def find_active(username):
    """활성 운영자면 {operator_id, username, display_name}, 아니면 None."""
    return db.row('SELECT operator_id, username, display_name FROM ap.operator WHERE username = %s AND is_active',
                  [username])
