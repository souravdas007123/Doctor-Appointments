from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from .forms import SignupForm
from .models import User


def signup(request):
    if request.user.is_authenticated:
        return redirect("accounts:redirect")
    form = SignupForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user)
        return redirect("accounts:redirect")
    return render(request, "accounts/signup.html", {"form": form})


@login_required
def role_redirect(request):
    """Login ke baad role ke hisaab se sahi dashboard bhejta hai."""
    role = request.user.role
    if role == User.Role.DOCTOR:
        return redirect("doctors:dashboard")
    if role == User.Role.PATIENT:
        return redirect("patients:dashboard")
    return redirect("admin:index")
