import logging

from django.contrib.auth import logout
from django.shortcuts import render

from . import operators

log = logging.getLogger('console.security')

# 화면은 같은 출처의 CSS만 쓴다. 스크립트·인라인 스타일·외부 자원·프레임 삽입을 모두 막는다.
CSP = ("default-src 'none'; style-src 'self'; img-src 'self'; form-action 'self'; "
       "base-uri 'none'; frame-ancestors 'none'")


class SecurityHeadersMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response.headers.setdefault('Content-Security-Policy', CSP)
        if not request.path.startswith('/static/'):
            # 개인정보·감사 기록이 담긴 화면을 브라우저 캐시에 남기지 않는다 (로그아웃 후 뒤로 가기 방지)
            response.headers.setdefault('Cache-Control', 'no-store')
        return response


class OperatorMiddleware:
    """NFR-14: 로그인 세션이 살아 있어도 매 요청마다 활성 운영자인지 DB에서 다시 확인한다.

    운영자가 비활성(is_active = false)이 되면 다음 요청에서 바로 세션을 끊는다.
    전이 기록에 남는 운영자 신원은 여기서 정한 request.operator 만 쓴다 (폼 입력을 믿지 않는다).
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.operator = None
        if request.path.startswith('/static/'):
            return self.get_response(request)
        if request.user.is_authenticated:
            operator = operators.find_active(request.user.get_username())
            if operator is None:
                log.warning('access revoked: user=%s path=%s', request.user.get_username(), request.path)
                logout(request)
                return render(request, 'console/denied.html', status=403)
            request.operator = operator
        return self.get_response(request)
