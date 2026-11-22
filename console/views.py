"""운영 콘솔 화면.

모든 화면은 로그인한 활성 운영자만 볼 수 있다(LoginRequiredMiddleware + OperatorMiddleware).
변경은 POST + CSRF 토큰으로만 받고, 기록에 남는 운영자는 request.operator 로만 정한다.
"""
import datetime
import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_not_required
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from . import actions, queries
from .forms import PasswordResetForm, TransitionForm

log = logging.getLogger('console.security')

ACCOUNT_TABS = [('timeline', '감사 타임라인'), ('sessions', '세션'), ('devices', '기기'),
                ('items', '아이템'), ('cases', '보호 케이스')]
STAT_PERIODS = [('7', '최근 7일', 7), ('30', '최근 30일', 30), ('all', '전체', None)]
EVIDENCE_FIELDS = [('state_label', '계정 상태'), ('credential_version', '자격증명 버전'),
                   ('transitions', '전이 기록 수'), ('last_transition_at', '마지막 전이 시각'),
                   ('open_cases', '진행 중 케이스 수'), ('credential_rows', '자격증명 이력 수'),
                   ('active_sessions', '유효 세션 수')]


def page_number(request):
    try:
        return max(1, int(request.GET.get('page', '1')))
    except ValueError:
        return 1


def show(value):
    if value is None:
        return '없음'
    if isinstance(value, datetime.datetime):
        return timezone.localtime(value).strftime('%Y-%m-%d %H:%M:%S')
    return str(value)


# ------------------------------------------------------------------ 위험 신호 큐 (REQ-05, 15)
@require_GET
def queue(request):
    rules = queries.risk_rules()
    rule = request.GET.get('rule', '')
    if rule not in {r['rule_code'] for r in rules}:
        rule = ''
    signals, page = queries.risk_queue(rule, page_number(request))
    return render(request, 'console/queue.html', {
        'nav': 'queue', 'rules': rules, 'rule': rule, 'signals': signals, 'page': page,
        'states': queries.state_counts(), 'open_total': sum(r['open'] for r in rules),
    })


@require_POST
def detect(request):
    try:
        created = actions.detect_all()
    except actions.Rejected as rej:
        return render(request, 'console/rejected.html', {'rej': rej, 'attempt': '전체 탐지 실행'}, status=rej.status)
    log.info('detect_all: operator=%s created=%s', request.operator['username'], created)
    messages.success(request, f'전체 로그인 이력에 탐지를 실행했습니다. 새로 만든 위험 신호 {created}건.')
    return redirect('console:queue')


# ------------------------------------------------------------------ 계정 (REQ-06, 12)
@require_GET
def accounts(request):
    states = queries.state_counts()
    search = request.GET.get('q', '').strip()[:60]
    state = request.GET.get('state', '')
    if state not in {s['state_code'] for s in states}:
        state = ''
    attention = request.GET.get('attention') == '1'
    found, page = queries.accounts(search, state, attention, page_number(request))
    return render(request, 'console/accounts.html', {
        'nav': 'accounts', 'accounts': found, 'page': page, 'states': states,
        'q': search, 'state': state, 'attention': attention,
    })


@require_GET
def account_detail(request, account_id):
    acc = queries.account(account_id)
    if acc is None:
        raise Http404
    tab = request.GET.get('tab', 'timeline')
    if tab not in dict(ACCOUNT_TABS):
        tab = 'timeline'
    transitions = queries.allowed_transitions(acc['state_code'])
    ctx = {
        'nav': 'accounts', 'acc': acc, 'tab': tab, 'tabs': ACCOUNT_TABS,
        'transitions': transitions, 'has_terminal': any(t['is_terminal'] for t in transitions),
        'signals': queries.account_signals(account_id),
    }

    done = request.GET.get('done', '')          # 방금 실행한 전이 "케이스-순번" → DB에서 다시 읽어 결과로 보여준다
    case_id, _, seq = done.partition('-')
    if case_id.isdigit() and seq.isdigit() and len(case_id) < 18 and len(seq) < 5:
        ctx['result'] = queries.transition_result(account_id, int(case_id), int(seq))

    if tab == 'timeline':
        event_filter = request.GET.get('ev', '')
        if event_filter not in queries.TIMELINE_FILTERS:
            event_filter = ''
        ctx['events'], ctx['page'] = queries.timeline(account_id, event_filter, page_number(request))
        ctx['event_filter'] = event_filter
        ctx['event_filters'] = [(key, label) for key, (label, _) in queries.TIMELINE_FILTERS.items()]
    elif tab == 'sessions':
        ctx['session_summary'], ctx['sessions'] = queries.sessions(account_id)
    elif tab == 'devices':
        ctx['devices'] = queries.devices(account_id)
    elif tab == 'items':
        ctx['items'] = queries.items(account_id)
    else:
        ctx['cases'], ctx['page'] = queries.cases('', account_id, page_number(request))
    return render(request, 'console/account_detail.html', ctx)


def rejected(request, rej, account_id, before, attempt):
    """REQ-16 예외 화면: 거부 사유와 함께, 요청 전후의 값을 나란히 보여 데이터가 그대로임을 확인하게 한다."""
    after = queries.evidence(account_id)
    evidence = [{'label': label, 'before': show(before[key]), 'after': show(after[key]),
                 'same': before[key] == after[key]} for key, label in EVIDENCE_FIELDS]
    log.warning('rejected: operator=%s account=%s attempt=%s code=%s',
                request.operator['username'], account_id, attempt, rej.code)
    return render(request, 'console/rejected.html', {
        'nav': 'accounts', 'rej': rej, 'attempt': attempt, 'account_id': account_id,
        'acc': queries.account(account_id), 'evidence': evidence,
        'unchanged': all(item['same'] for item in evidence),
    }, status=rej.status)


@require_POST
def transition(request, account_id):
    """REQ-07. 사유·허용 여부는 화면에서 다시 검사하지 않고 DB 함수에 맡긴다."""
    before = queries.evidence(account_id)
    if before is None:
        raise Http404
    form = TransitionForm(request.POST)
    to_state = request.POST.get('to_state', '')[:20]
    attempt = f'상태 전이 {before["state_code"]} → {to_state or "(선택 없음)"}'
    try:
        if not form.is_valid():
            raise actions.Rejected('INVALID_REQUEST', '잘못된 요청',
                                   '전이 대상을 고르지 않았거나 사유가 500자를 넘었습니다.', '화면 검증', status=400)
        data = form.cleaned_data
        target = next((t for t in queries.allowed_transitions(before['state_code'])
                       if t['to_state'] == data['to_state']), None)
        if target and target['is_terminal'] and not data['confirm_terminal']:
            raise actions.Rejected('CONFIRM_REQUIRED', '확인 필요',
                                   f'「{target["to_label"]}」은 되돌릴 수 없는 종착 상태입니다. '
                                   '확인란에 표시한 뒤 다시 실행하세요.', '화면 검증', status=400)
        result = actions.transition(account_id, data['to_state'], data['expected_state'],
                                    request.operator['operator_id'], data['reason'])
    except actions.Rejected as rej:
        return rejected(request, rej, account_id, before, attempt)
    log.info('transition: operator=%s account=%s %s->%s case=%s seq=%s', request.operator['username'], account_id,
             result['from_state'], result['to_state'], result['case_id'], result['seq'])
    return redirect(f'{reverse("console:account", args=[account_id])}?done={result["case_id"]}-{result["seq"]}')


@require_POST
def reset_password(request, account_id):
    """REQ-10. 입력한 비밀번호는 화면에 다시 내보내지 않고 로그에도 남기지 않는다."""
    before = queries.evidence(account_id)
    if before is None:
        raise Http404
    form = PasswordResetForm(request.POST)
    try:
        if not form.is_valid():
            raise actions.Rejected('PASSWORD_MISMATCH', '입력 확인 필요',
                                   '새 비밀번호와 확인 입력이 서로 다르거나 비어 있습니다.', '화면 검증', status=400)
        version = actions.reset_password(account_id, form.cleaned_data['new_password'],
                                         request.operator['operator_id'])
    except actions.Rejected as rej:
        return rejected(request, rej, account_id, before, '복구용 비밀번호 재설정')
    log.info('reset_password: operator=%s account=%s version=%s', request.operator['username'], account_id, version)
    messages.success(request, f'새 비밀번호를 설정했습니다. 자격증명 버전이 {version}(으)로 올라갔고, '
                              f'{request.operator["display_name"]} 이름으로 기록되었습니다.')
    return redirect('console:account', account_id)


# ------------------------------------------------------------------ 보호 케이스
@require_GET
def cases(request):
    status = request.GET.get('status', 'open')
    if status not in ('open', 'closed', 'all'):
        status = 'open'
    found, page = queries.cases(status, None, page_number(request))
    return render(request, 'console/cases.html', {'nav': 'cases', 'cases': found, 'page': page, 'status': status})


@require_GET
def case_detail(request, case_id):
    case = queries.case(case_id)
    if case is None:
        raise Http404
    snapshot = queries.case_snapshot(case_id)
    return render(request, 'console/case_detail.html', {
        'nav': 'cases', 'case': case, 'transitions': queries.case_transitions(case_id),
        'signals': queries.case_signals(case_id), 'snapshot': snapshot,
        'moved': sum(1 for item in snapshot if not item['still_owned']),
    })


# ------------------------------------------------------------------ 통계 (REQ-14)
@require_GET
def stats(request):
    period = request.GET.get('period', '30')
    days = next((d for key, _, d in STAT_PERIODS if key == period), 30)
    if period not in {key for key, _, _ in STAT_PERIODS}:
        period = '30'
    states = queries.state_counts()
    transitions = queries.stats_transitions(days)
    signals = queries.stats_signals(days)
    return render(request, 'console/stats.html', {
        'nav': 'stats', 'period': period, 'periods': STAT_PERIODS,
        'states': states, 'state_max': max([s['n'] for s in states] + [1]),
        'signals': signals, 'signal_max': max([s['total'] for s in signals if not s['is_total']] + [1]),
        'transitions': transitions, 'transition_max': max([t['n'] for t in transitions] + [1]),
        'operators': queries.stats_operators(days), 'cases': queries.stats_cases(),
    })


# ------------------------------------------------------------------ 오류 화면
@login_not_required
def not_found(request, exception=None):
    return render(request, 'console/404.html', status=404)


@login_not_required
def server_error(request):
    return render(request, 'console/500.html', status=500)


@login_not_required
def csrf_failure(request, reason=''):
    log.warning('csrf failure: path=%s reason=%s', request.path, reason)
    return render(request, 'console/403_csrf.html', status=403)
