from django.urls import path

from . import views

app_name = "medical"
urlpatterns = [
    path("record/<int:appointment_id>/", views.record_view, name="record_view"),
    path("record/<int:appointment_id>/edit/", views.record_edit, name="record_edit"),
    path("prescription/<int:appointment_id>/", views.prescription_view, name="prescription_view"),
    path("prescription/<int:appointment_id>/edit/", views.prescription_edit, name="prescription_edit"),
    path("prescription/<int:appointment_id>/pdf/", views.prescription_pdf, name="prescription_pdf"),
]
