from django.urls import path

from . import views

app_name = "notifications"
urlpatterns = [
    path("", views.list_notifications, name="list"),
    path("mark-all-read/", views.mark_all_read, name="mark_all_read"),
    path("<int:pk>/open/", views.open_notification, name="open"),
]
