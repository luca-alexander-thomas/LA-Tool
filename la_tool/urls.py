"""URL-Konfiguration: App unter /, eigener Admin-Bereich unter /admin/ (Django-Admin nur mit DEBUG)."""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('', include('app.urls')),
    path('admin/', include('la_tool_admin.urls')),
]

urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

if settings.DEBUG:
    urlpatterns += path('django-admin/', admin.site.urls),
