from django.contrib.auth import views as auth_views
from django.urls import path

from . import views
from .forms import EmailLoginForm

app_name = "accounts"

urlpatterns = [
    path("", views.role_redirect, name="redirect"),
    path("signup/", views.signup, name="signup"),
    path("login/", auth_views.LoginView.as_view(
        template_name="registration/login.html", authentication_form=EmailLoginForm,
        redirect_authenticated_user=True), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
]
