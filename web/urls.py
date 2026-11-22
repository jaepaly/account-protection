from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_not_required
from django.contrib.staticfiles.views import serve as serve_static
from django.urls import include, path, re_path

from console.forms import OperatorAuthenticationForm

urlpatterns = [
    path('login/', auth_views.LoginView.as_view(authentication_form=OperatorAuthenticationForm,
                                                redirect_authenticated_user=True), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),      # POST 전용 (Django 5)
    # 로컬 데모용 정적 파일 제공: DEBUG 를 끈 채로도 runserver 하나로 화면이 나오게 한다.
    re_path(r'^static/(?P<path>.*)$', login_not_required(serve_static), {'insecure': True}),
    path('', include('console.urls')),
]

handler404 = 'console.views.not_found'
handler500 = 'console.views.server_error'
