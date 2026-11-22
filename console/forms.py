import logging

from django import forms
from django.contrib.auth.forms import AuthenticationForm
from django.core.exceptions import ValidationError

from . import operators

log = logging.getLogger('console.security')


class OperatorAuthenticationForm(AuthenticationForm):
    """비밀번호가 맞아도 활성 운영자(ap.operator)가 아니면 로그인시키지 않는다.

    거부 사유(없는 아이디 / 틀린 비밀번호 / 운영자 아님)를 화면에서 구분하지 않는다.
    """
    error_messages = {
        'invalid_login': '아이디 또는 비밀번호가 올바르지 않습니다.',
        'inactive': '아이디 또는 비밀번호가 올바르지 않습니다.',
    }

    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)
        if operators.find_active(user.get_username()) is None:
            log.warning('login denied (not an active operator): user=%s', user.get_username())
            raise ValidationError(self.error_messages['invalid_login'], code='invalid_login')


class TransitionForm(forms.Form):
    to_state = forms.CharField(max_length=20)
    expected_state = forms.CharField(max_length=20)      # 운영자가 화면에서 본 상태 — 그 사이 바뀌었으면 거부
    reason = forms.CharField(max_length=500, required=False)   # 빈 사유는 DB가 거부한다(REASON_REQUIRED)
    confirm_terminal = forms.BooleanField(required=False)


class PasswordResetForm(forms.Form):
    new_password = forms.CharField(max_length=128, strip=False)
    confirm_password = forms.CharField(max_length=128, strip=False)

    def clean(self):
        data = super().clean()
        if data.get('new_password') != data.get('confirm_password'):
            raise ValidationError('두 입력이 서로 다릅니다.', code='mismatch')
        return data
