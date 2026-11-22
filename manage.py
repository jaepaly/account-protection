#!/usr/bin/env python
"""Django 관리 명령 진입점.

    python manage.py migrate            # Django 자체 테이블(public 스키마) 생성
    python manage.py sync_operators     # ap.operator → 웹 로그인 계정
    python manage.py runserver 8000
"""
import os
import sys


def main():
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'web.settings')
    from django.core.management import execute_from_command_line
    execute_from_command_line(sys.argv)


if __name__ == '__main__':
    main()
