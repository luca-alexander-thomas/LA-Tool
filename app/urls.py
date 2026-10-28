from django.urls import path

from . import views, pwa
from la_tool_admin import views as views_admin

urlpatterns = [
    path('manifest.webmanifest', pwa.manifest, name='manifest'),
    path('sw.js', pwa.service_worker, name='service_worker'),
    path('offline/', pwa.offline, name='offline'),
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
