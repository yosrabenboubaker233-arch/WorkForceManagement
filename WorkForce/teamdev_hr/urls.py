from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("accounts.urls")),
    path("employes/", include("employees.urls")),
    path("conges/", include("leaves.urls")),
    path("pointage/", include("attendance.urls")),
    path("paie/", include("payroll.urls")),
    path("notifications/", include("notifications.urls")),
    path("taches/", include("tasks.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
