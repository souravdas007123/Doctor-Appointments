from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("apps.accounts.urls")),
    path("patient/", include("apps.patients.urls")),
    path("doctor/", include("apps.doctors.urls")),
    path("appointments/", include("apps.appointments.urls")),
    path("payments/", include("apps.payments.urls")),
    path("medical/", include("apps.medical.urls")),
    path("notifications/", include("apps.notifications.urls")),
]
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
