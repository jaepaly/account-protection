"""ap.operator(업무 테이블) → Django 웹 로그인 계정 동기화.

    python manage.py sync_operators                    # 없는 계정을 만든다
    python manage.py sync_operators --reset-passwords  # 모든 운영자 비밀번호를 초기값으로 되돌린다

- 사용자명이 같으면 같은 사람이다(operator.username = auth_user.username).
- 처음 만드는 계정의 비밀번호는 .env 의 AP_WEB_OPERATOR_PASSWORD (화면에 출력하지 않는다).
  개인 비밀번호로 바꾸려면: python manage.py changepassword <사용자명>
- 운영자가 비활성이거나 없어진 웹 계정은 비활성으로 바꾼다. 관리자 권한(is_staff, is_superuser)은 주지 않는다.
"""
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from console import db
from dbconf import ENV


class Command(BaseCommand):
    help = 'ap.operator 의 운영자를 웹 로그인 계정으로 동기화한다.'

    def add_arguments(self, parser):
        parser.add_argument('--reset-passwords', action='store_true', help='기존 계정의 비밀번호도 초기값으로 되돌린다')

    def handle(self, *args, **options):
        password = ENV.get('AP_WEB_OPERATOR_PASSWORD', '')
        if len(password) < 10:
            raise CommandError('.env 의 AP_WEB_OPERATOR_PASSWORD 를 10자 이상으로 정해 주세요.')
        User = get_user_model()
        operators = db.rows('SELECT username, display_name, is_active FROM ap.operator ORDER BY operator_id')
        names = set()
        for op in operators:
            names.add(op['username'])
            user, created = User.objects.get_or_create(username=op['username'])
            if created or options['reset_passwords']:
                user.set_password(password)
            user.first_name = op['display_name']
            user.is_active = op['is_active']
            user.is_staff = user.is_superuser = False
            user.save()
            state = '생성' if created else ('비밀번호 초기화' if options['reset_passwords'] else '유지')
            self.stdout.write(f'  {op["username"]:<12} {op["display_name"]:<8} {"활성" if op["is_active"] else "비활성"}  {state}')
        orphaned = User.objects.exclude(username__in=names).filter(is_active=True)
        for user in orphaned:
            user.is_active = False
            user.save(update_fields=['is_active'])
            self.stdout.write(f'  {user.username:<12} 운영자 목록에 없음 → 웹 계정 비활성')
        self.stdout.write(self.style.SUCCESS(f'운영자 {len(operators)}명 동기화 완료'))
