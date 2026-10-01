from django.urls import path

from . import views

app_name = "payments"
urlpatterns = [
    path("", views.my_payments, name="list"),
    path("checkout/<int:appointment_id>/", views.checkout, name="checkout"),
    path("verify/", views.verify, name="verify"),
    path("webhook/", views.webhook, name="webhook"),
]
