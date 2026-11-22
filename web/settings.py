"""Django 설정 — 계정 보호 운영 콘솔.

DB 접속 정보는 .env 에서 읽는다(scripts/dbconf.py 와 같은 규칙, 환경변수가 우선).
웹은 최소 권한 역할 ap_ops 로만 접속한다 (db/04_grants.sql):
  - public 스키마: Django 자체 테이블(인증·세션) — ap_ops 소유
  - ap 스키마    : 업무 데이터 — 조회(민감 컬럼 제외)와 정책 함수 실행만 가능.
                   INSERT/UPDATE/DELETE 권한이 없으므로 화면 코드에 실수가 있어도 정책을 우회할 수 없다.
"""
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / 'scripts'))
from dbconf import ENV, db_name  # noqa: E402

DEBUG = ENV.get('AP_WEB_DEBUG', '0') == '1'          # 기본은 끔: 오류 화면에 내부 정보(SQL·설정)를 노출하지 않는다
HTTPS = ENV.get('AP_WEB_HTTPS', '0') == '1'          # 로컬 http 데모에서는 끔. 배포 시 1
SECRET_KEY = ENV['AP_WEB_SECRET_KEY']
ALLOWED_HOSTS = ['127.0.0.1', 'localhost']

INSTALLED_APPS = [
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'console',
]   # django.contrib.admin 은 넣지 않는다 — 운영자 계정은 관리 명령으로만 만든다

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'console.middleware.SecurityHeadersMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.auth.middleware.LoginRequiredMiddleware',   # 기본 거부: 로그인 화면 외의 모든 요청에 로그인 요구
    'console.middleware.OperatorMiddleware',                    # 매 요청마다 활성 운영자인지 DB에서 다시 확인
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'web.urls'
WSGI_APPLICATION = 'web.wsgi.application'

TEMPLATES = [{
    'BACKEND': 'django.template.backends.django.DjangoTemplates',
    'DIRS': [],
    'APP_DIRS': True,
    'OPTIONS': {'context_processors': [
        'django.template.context_processors.request',
        'django.contrib.auth.context_processors.auth',
        'django.contrib.messages.context_processors.messages',
    ]},
}]

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'HOST': ENV.get('PG_HOST', '127.0.0.1'),
        'PORT': ENV.get('PG_PORT', '5433'),
        'NAME': db_name(os.environ.get('AP_DB_TARGET') or ENV.get('AP_DB_TARGET', 'dev')),   # test = 테스트 DB
        'USER': 'ap_ops',
        'PASSWORD': ENV['AP_OPS_PASSWORD'],
        'OPTIONS': {
            'connect_timeout': 5,
            # 매개변수를 SQL 문자열에 끼워 넣지 않고 따로 보낸다 — 입력한 비밀번호가 서버 로그의 SQL 문에 남지 않는다.
            'server_side_binding': True,
            # search_path 에 ap 를 넣지 않는다 — 업무 객체는 항상 ap. 로 명시한다.
            # lock_timeout: 같은 계정의 로그인·이동과 겹쳐 잠금을 기다릴 때 무한정 멈추지 않게 한다.
            'options': '-c search_path=public -c statement_timeout=15000 -c lock_timeout=5000',
        },
    },
}
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator', 'OPTIONS': {'min_length': 10}},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]
LOGIN_URL = 'login'
LOGIN_REDIRECT_URL = 'console:queue'
LOGOUT_REDIRECT_URL = 'login'

# 세션: 60분 동안 요청이 없으면 만료, 브라우저를 닫으면 삭제
SESSION_COOKIE_AGE = 60 * 60
SESSION_SAVE_EVERY_REQUEST = True
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Strict'
CSRF_COOKIE_SAMESITE = 'Strict'
CSRF_FAILURE_VIEW = 'console.views.csrf_failure'
SESSION_COOKIE_SECURE = CSRF_COOKIE_SECURE = SECURE_SSL_REDIRECT = HTTPS
SECURE_HSTS_SECONDS = 31536000 if HTTPS else 0
X_FRAME_OPTIONS = 'DENY'
SECURE_REFERRER_POLICY = 'same-origin'

LANGUAGE_CODE = 'ko-kr'
TIME_ZONE = 'Asia/Seoul'
USE_I18N = True
USE_TZ = True

STATIC_URL = 'static/'

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {'line': {'format': '%(asctime)s %(levelname)s %(name)s %(message)s'}},
    'handlers': {'console': {'class': 'logging.StreamHandler', 'formatter': 'line'}},
    'loggers': {'console': {'handlers': ['console'], 'level': 'INFO'}},   # 로그인 거부·처리 거부 등 보안 이벤트
}
