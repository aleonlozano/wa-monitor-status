from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from monitor import views as monitor_views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('monitor.urls')),
    path('', monitor_views.home, name='home'),
    path('wa/start-session/', monitor_views.wa_start_session, name='wa_start_session'),
    path('api/wa-status/', monitor_views.wa_status_api, name='wa_status_api'),
    path('wa/logout/', monitor_views.wa_logout, name='wa_logout'),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
