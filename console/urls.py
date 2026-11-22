from django.urls import path, register_converter

from . import views


class IdConverter:
    """bigint 범위를 넘지 않는 양의 정수 (자릿수 제한으로 DB 범위 오류를 막는다)."""
    regex = '[0-9]{1,18}'

    def to_python(self, value):
        return int(value)

    def to_url(self, value):
        return str(value)


register_converter(IdConverter, 'id')

app_name = 'console'
urlpatterns = [
    path('', views.queue, name='queue'),
    path('detect/', views.detect, name='detect'),
    path('accounts/', views.accounts, name='accounts'),
    path('accounts/<id:account_id>/', views.account_detail, name='account'),
    path('accounts/<id:account_id>/transition/', views.transition, name='transition'),
    path('accounts/<id:account_id>/password/', views.reset_password, name='reset_password'),
    path('cases/', views.cases, name='cases'),
    path('cases/<id:case_id>/', views.case_detail, name='case'),
    path('stats/', views.stats, name='stats'),
]
