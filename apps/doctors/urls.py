from django.urls import path

from . import views

app_name = "doctors"
urlpatterns = [
    path("dashboard/", views.dashboard, name="dashboard"),
    path("profile/", views.profile_edit, name="profile"),
    path("availability/", views.availability, name="availability"),
    path("availability/<int:pk>/delete/", views.availability_delete, name="availability_delete"),
    path("time-off/", views.time_off, name="time_off"),
    path("time-off/<int:pk>/delete/", views.time_off_delete, name="time_off_delete"),
]
