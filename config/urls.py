from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

# Admin role ke liye "/" khud role_redirect() se guzar ke seedha wapas admin:index par bhej deta hai
# (is app mein admin ke liye koi alag patient/doctor jaisa "site" nahi hai -- by design). Isliye Django
# admin ka built-in "View site" link sirf ek dead loop tha (click karo to / pe jaake turant wapas
# /admin/ bounce ho jaata). site_url=None us link ko hi hata deta hai, taaki confusing na lage.
admin.site.site_url = None

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
