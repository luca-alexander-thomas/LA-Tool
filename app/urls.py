from django.templatetags.static import static
from django.urls import path, re_path
from django.views.generic import RedirectView

from . import views, pwa
from la_tool_admin import views as views_admin

urlpatterns = [
    # Browser fragen diese Icons fest an der Wurzel ab (iOS: auch mit Größe/-precomposed)
    path('favicon.ico', RedirectView.as_view(url=static('pwa/favicon.png'), permanent=True)),
    re_path(r'^apple-touch-icon(?:-\d+x\d+)?(?:-precomposed)?\.png$',
            RedirectView.as_view(url=static('pwa/apple-touch-icon.png'), permanent=True)),
    path('manifest.webmanifest', pwa.manifest, name='manifest'),
    path('sw.js', pwa.service_worker, name='service_worker'),
    path('offline/', pwa.offline, name='offline'),
    path('healthz/', views.health, name='health'),
    path('push/abonnieren/', pwa.push_subscribe, name='push_subscribe'),
    path('push/abbestellen/', pwa.push_unsubscribe, name='push_unsubscribe'),
    path('push/test/', pwa.push_test, name='push_test'),
    path('', views.index, name='home'),
    path('first-run/', views.first_run_wizard, name='first_run_wizard'),
    path('login/', views.login, name='login'),
    path('profile/', views.profile, name='profile'),
    path('logout/', views.logout, name='logout'),
    path('microsoft-login/', views_admin.microsoft_login, name='microsoft_login'),
    path('microsoft-callback/', views_admin.microsoft_callback,
         name='microsoft_callback'),
    path('pruefungen/', views.exam_list, name='exam_list'),
    path('pruefungen/<int:exam_id>/', views.exam_start, name='exam_start'),
    path('pruefungen/<int:exam_id>/run/', views.exam_run, name='exam_run'),
    path('pruefungen/<int:exam_id>/ergebnis/', views.exam_result, name='exam_result'),
    path('uebungen/', views.excercise, name='excercise'),
    path('uebungen/theorie/', views.training_config, name='training_config'),
    path('uebungen/theorie/fragen/', views.theory_lookup, name='theory_lookup'),
    path('uebungen/theorie/fragen/offline/', views.theory_offline_page, name='theory_offline_page'),
    path('uebungen/theorie/fragen/offline.json', views.theory_offline_data, name='theory_offline_data'),
    path('benachrichtigungen/', views.notification_list, name='notification_list'),
    path('benachrichtigungen/<int:notification_id>/', views.notification_open, name='notification_open'),
    path('uebungen/theorie/fragen/<int:q_id>/merken/', views.question_bookmark, name='question_bookmark'),
    path('uebungen/theorie/fragen/<int:q_id>/melden/', views.question_report, name='question_report'),
    path('uebungen/theorie/heute/', views.training_today, name='training_today'),
    path('uebungen/theorie/lernstand/', views.learning_stats, name='learning_stats'),
    path('uebungen/theorie/training/<int:result_id>/wiederholen/', views.training_retry, name='training_retry'),
    path('uebungen/theorie/training/', views.training_run, name='training_run'),
    path('uebungen/theorie/training/<int:result_id>/', views.training_result, name='training_result'),
    path('uebungen/praxis/', views.practical_list, name='practical_list'),
    path('uebungen/praxis/<int:q_id>/', views.practical_detail, name='practical_detail'),
    path('uebungen/gruppen/', views.group_list, name='group_list'),
    path('uebungen/gruppen/<int:q_id>/', views.group_detail, name='group_detail'),
    path('dienste/', views.work_list, name='work'),
    path('dienste/<int:work_id>/', views.work_detail, name='work_detail'),
    path('dienste/<int:work_id>/ueben/', views.work_training_start, name='work_training_start'),
    path('la-filter/<str:level>/', views.set_la_filter, name='set_la_filter'),
]
