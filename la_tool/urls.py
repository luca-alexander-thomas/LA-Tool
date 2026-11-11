"""URL-Konfiguration: App unter /, eigener Admin-Bereich unter /admin/ (Django-Admin nur mit DEBUG)."""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.urls import re_path
from django.views.static import serve

urlpatterns = [
    path('', include('app.urls')),
    path('admin/', include('la_tool_admin.urls')),
    # Uploads liefert Django selbst aus (auch ohne DEBUG): Der Proxy sieht das Volume im Container nicht.
    # Inhalte sind ohnehin öffentlich (Praxis-/Gruppenaufgaben, Stufen-Icons); die Menge ist klein.
    re_path(r'^media/(?P<path>.*)$', serve, {'document_root': settings.MEDIA_ROOT}),
]

if settings.DEBUG:
    urlpatterns += path('django-admin/', admin.site.urls),
