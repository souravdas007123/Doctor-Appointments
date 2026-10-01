from django.urls import path

from . import views

app_name = "patients"
urlpatterns = [
    path("dashboard/", views.dashboard, name="dashboard"),
    path("profile/", views.profile_edit, name="profile"),
    path("doctors/", views.doctor_list, name="doctor_list"),
    path("doctors/<int:pk>/", views.doctor_detail, name="doctor_detail"),
    path("medical-records/", views.medical_records, name="medical_records"),
    path("prescriptions/", views.prescriptions, name="prescriptions"),
]
