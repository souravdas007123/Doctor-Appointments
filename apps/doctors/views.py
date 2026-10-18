from django.contrib import messages
from django.db.models import Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.accounts.decorators import role_required
from apps.appointments.models import Appointment, AppointmentStatus
from apps.payments.models import Payment

from .forms import AvailabilityForm, BlockedSlotForm, DoctorProfileForm
from .models import DoctorAvailability, DoctorBlockedSlot

# In fields ke badalne par verification dobara chahiye
VERIFIED_FIELDS = {"license_number", "qualification"}


@role_required("doctor")
def dashboard(request):
    profile = request.user.doctor_profile
    if not profile.is_verified:
        return render(request, "doctors/pending.html", {"profile": profile})
    S = AppointmentStatus
    mine = Appointment.objects.filter(doctor=profile)
    todays = (
        mine.filter(appointment_date=timezone.localdate()).exclude(status=S.CANCELLED)
        .select_related("patient__user").order_by("start_time")
    )
    stats = {
        "today": todays.count(),
        "patients": mine.filter(status__in=[S.CONFIRMED, S.IN_PROGRESS, S.COMPLETED]).values("patient").distinct().count(),
        "revenue": Payment.objects.filter(appointment__doctor=profile, status=Payment.Status.PAID).aggregate(total=Sum("amount"))["total"] or 0,
    }
    return render(request, "doctors/dashboard.html", {"profile": profile, "stats": stats, "todays": todays})


@role_required("doctor")
def profile_edit(request):
    profile = request.user.doctor_profile
    form = DoctorProfileForm(request.POST or None, instance=profile)
    if request.method == "POST" and form.is_valid():
        was_verified = profile.is_verified
        profile = form.save(commit=False)
        if was_verified and VERIFIED_FIELDS & set(form.changed_data):
            profile.is_verified = False
            profile.verified_at = None
            messages.warning(request, "License/qualification badle hain, isliye admin verification dobara hoga.")
        profile.save()
        messages.success(request, "Profile save ho gaya.")
        return redirect("doctors:profile")
    return render(request, "doctors/profile.html", {"form": form, "profile": profile})


@role_required("doctor")
def availability(request):
    doctor = request.user.doctor_profile
    form = AvailabilityForm(request.POST or None, doctor=doctor)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Availability add ho gayi.")
        return redirect("doctors:availability")
    windows = list(doctor.availabilities.all())
    days = [(label, [w for w in windows if w.weekday == value]) for value, label in DoctorAvailability.Weekday.choices]
    return render(request, "doctors/availability.html", {"form": form, "days": days, "doctor": doctor})


@require_POST
@role_required("doctor")
def availability_delete(request, pk):
    obj = get_object_or_404(DoctorAvailability, pk=pk, doctor=request.user.doctor_profile)
    obj.delete()
    messages.success(request, "Window hata di gayi.")
    return redirect("doctors:availability")


@role_required("doctor")
def time_off(request):
    doctor = request.user.doctor_profile
    form = BlockedSlotForm(request.POST or None, doctor=doctor)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Time off add ho gaya.")
        return redirect("doctors:time_off")
    upcoming = doctor.blocked_slots.filter(date__gte=timezone.localdate())
    return render(request, "doctors/time_off.html", {"form": form, "upcoming": upcoming})


@require_POST
@role_required("doctor")
def time_off_delete(request, pk):
    obj = get_object_or_404(DoctorBlockedSlot, pk=pk, doctor=request.user.doctor_profile)
    obj.delete()
    messages.success(request, "Time off hata diya gaya.")
    return redirect("doctors:time_off")
