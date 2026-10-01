from django.urls import path

from . import views

app_name = "appointments"
urlpatterns = [
    path("", views.my_appointments, name="list"),
    path("book/", views.book, name="book"),
    path("doctor/", views.doctor_appointments, name="doctor_list"),
    path("<int:pk>/", views.detail, name="detail"),
    path("<int:pk>/cancel/", views.cancel, name="cancel"),
    path("<int:pk>/reschedule/", views.reschedule, name="reschedule"),
    path("<int:pk>/status/", views.update_status, name="update_status"),
]
