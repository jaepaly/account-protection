from django import template
from django.utils.html import format_html

register = template.Library()

EVENTS = {
    'LOGIN_SUCCESS': ('로그인 성공', 'ok'),
    'LOGIN_FAILED': ('로그인 실패', 'warn'),
    'RISK_SIGNAL': ('위험 신호', 'alert'),
    'STATE_TRANSITION': ('상태 전이', 'info'),
    'SESSION_REVOKED': ('세션 폐기', 'info'),
    'TRANSFER_APPROVED': ('이동 승인', 'ok'),
    'TRANSFER_REJECTED': ('이동 거절', 'warn'),
}
SESSION_STATUS = {'ACTIVE': ('유효', 'ok'), 'REVOKED': ('폐기', 'info'), 'EXPIRED': ('만료', 'quiet'),
                  'STALE_CREDENTIAL': ('무효 · 자격증명 변경', 'warn')}
REVOKE_REASON = {'LOGOUT': '로그아웃', 'STATE_TRANSITION': '상태 전이'}
RARITY = {'COMMON': '일반', 'RARE': '희귀', 'EPIC': '영웅', 'LEGENDARY': '전설'}
SEVERITY = {1: '낮음', 2: '중간', 3: '높음'}
CREDENTIAL_REASON = {'INITIAL': '최초 설정', 'USER_CHANGE': '본인 변경', 'FORCED_ROTATION': '보호 조치로 폐기',
                     'RECOVERY_RESET': '복구 재설정'}


@register.simple_tag
def state_badge(code, label):
    return format_html('<span class="badge state state-{}">{}</span>', code, label)


@register.simple_tag
def severity_badge(level):
    return format_html('<span class="badge sev sev-{}">{}</span>', level, SEVERITY.get(level, level))


@register.simple_tag
def event_badge(event_type):
    label, tone = EVENTS.get(event_type, (event_type, 'quiet'))
    return format_html('<span class="badge tone-{}">{}</span>', tone, label)


@register.simple_tag
def session_badge(status):
    label, tone = SESSION_STATUS.get(status, (status, 'quiet'))
    return format_html('<span class="badge tone-{}">{}</span>', tone, label)


@register.simple_tag
def bar(value, maximum, tone='accent'):
    """가로 막대 (인라인 스타일 없이 SVG 속성으로 길이를 준다 — CSP 가 인라인 스타일을 막기 때문)."""
    percent = round(100 * value / maximum) if maximum else 0
    return format_html('<svg class="bar bar-{}" viewBox="0 0 100 8" preserveAspectRatio="none" aria-hidden="true">'
                       '<rect class="bar-track" width="100" height="8"/><rect class="bar-fill" width="{}" height="8"/></svg>',
                       tone, percent)


@register.filter
def rarity_label(code):
    return RARITY.get(code, code)


@register.filter
def revoke_label(code):
    return REVOKE_REASON.get(code, code or '')


@register.filter
def credential_label(code):
    return CREDENTIAL_REASON.get(code, code)


@register.filter
def duration(delta):
    """timedelta → '2일 3시간' / '41분'."""
    if delta is None:
        return '—'
    minutes = int(delta.total_seconds() // 60)
    days, minutes = divmod(minutes, 1440)
    hours, minutes = divmod(minutes, 60)
    if days:
        return f'{days}일 {hours}시간'
    if hours:
        return f'{hours}시간 {minutes}분'
    return f'{minutes}분'
