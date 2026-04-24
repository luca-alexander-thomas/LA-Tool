from django.urls import path
from . import views

urlpatterns = [
    path('', views.index, name='admin_index'),
    path('catalog/', views.admin_catalog, name='admin_catalog'),
    path('catalog/<str:vtype>/', views.admin_catalog, name='admin_catalog_edit'),
    path('users/', views.admin_users, name='admin_users'),
    path('exam/', views.admin_exam, name='admin_exam'),
    path('exam/<str:vtype>/', views.admin_exam, name='admin_exam'),
    path('work', views.admin_work, name='admin_work'),
    path('work/<str:vtype>/', views.admin_work, name='admin_work_edit'),

]
