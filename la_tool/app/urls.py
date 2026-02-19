from django.urls import path

from . import views

urlpatterns = [
    path('', views.index, name='home'),
    path('login/', views.login, name='login'),
    path('profile/', views.profile, name='profile'),
    path('logout/', views.logout, name='logout'),
    path('microsoft-login/', views.microsoft_login, name='microsoft_login'),
    path('microsoft-callback/', views.microsoft_callback, name='microsoft_callback'),
]
